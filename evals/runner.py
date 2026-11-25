"""Run a golden set through the harness and score it.

The matrix (retriever x model x delivery mode) is run by calling this once per
configuration, e.g. with different BRAIN_PLANNER_MODEL values or --index, and
comparing the summaries. Each run writes per-item JSONL next to the summary.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from evals.scorers import score_item, summarize


def load_golden(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get("items", [])
    ids = [i["id"] for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate ids in {path}")
    return items


async def _run_all(harness: Any, items: list[dict[str, Any]], concurrency: int) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)

    async def one(item: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                result = await harness.ask(item["question"])
                record = result.record
            except Exception as exc:  # scored as a failure, never hidden
                return {"error": f"{type(exc).__name__}: {exc}"}
            data = json.loads(record.to_json())
            return data

    return await asyncio.gather(*(one(i) for i in items))


def run_golden(harness: Any, golden: Path, out_dir: Path, concurrency: int = 4) -> dict[str, Any]:
    items = load_golden(golden)
    records = asyncio.run(_run_all(harness, items, concurrency))
    scores = [score_item(item, rec) for item, rec in zip(items, records, strict=True)]
    summary = summarize(scores)
    summary["models"] = next((r.get("models") for r in records if r.get("models")), {})
    summary["index"] = harness.index is not None

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{stamp}-items.jsonl").open("w", encoding="utf-8") as fh:
        for score, rec in zip(scores, records, strict=True):
            fh.write(json.dumps({"score": asdict(score), "record": rec}, default=str) + "\n")
    (out_dir / f"{stamp}-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
