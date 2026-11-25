from __future__ import annotations

from pathlib import Path

from evals.runner import load_golden
from evals.scorers import score_item, summarize

ROOT = Path(__file__).resolve().parents[2]


def _record(paths, text="", abstained=False, validity=1.0):
    return {
        "answer": {"answer": text, "abstained": abstained, "citations": [{"path": p} for p in paths]},
        "citation_validity": validity,
        "tool_calls": {"grep:x": 2},
    }


def test_golden_set_loads():
    items = load_golden(ROOT / "evals" / "golden" / "example.yaml")
    assert {i["kind"] for i in items} >= {"lookup", "conflict", "absent"}


def test_conflict_item_fails_when_deprecated_cited():
    item = {
        "id": "c",
        "kind": "conflict",
        "expect_paths": ["a.md"],
        "must_not_cite": ["old.md"],
        "expect_any": ["grep"],
    }
    assert score_item(item, _record(["a.md"], "grep first")).passed
    assert not score_item(item, _record(["a.md", "old.md"], "grep first")).passed


def test_abstain_and_summary():
    absent = {"id": "a", "kind": "absent", "expect_abstain": True}
    scores = [
        score_item(absent, _record([], abstained=True)),
        score_item({"id": "b", "expect_paths": ["x.md"]}, _record([], "nothing")),
    ]
    summary = summarize(scores)
    assert summary["abstain_accuracy"] == 1.0
    assert summary["failed"] == ["b"]
    assert summary["gates_passed"] is False
