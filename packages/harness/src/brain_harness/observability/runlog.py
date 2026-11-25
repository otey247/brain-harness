"""One JSON line per run: question, answer, citations, evidence, usage, timings.

The run log is what evals and regressions read. It never holds secrets: tool
arguments and bundle paths only, plus the final answer.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class RunRecord:
    question: str
    bundle: str
    models: dict[str, str]
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    duration_s: float = 0.0
    answer: dict[str, Any] | None = None
    citation_validity: float | None = None
    opened: list[str] = field(default_factory=list)
    grep_hits: list[str] = field(default_factory=list)
    tool_calls: dict[str, int] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    _t0: float = field(default_factory=time.perf_counter, repr=False)

    def finish(self) -> None:
        self.duration_s = round(time.perf_counter() - self._t0, 3)

    def to_json(self) -> str:
        data = asdict(self)
        data.pop("_t0", None)
        return json.dumps(data, default=str)


class RunLog:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def write(self, record: RunRecord) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{datetime.now(UTC).date().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")
        return path
