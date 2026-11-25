"""Deterministic scorers. A model-graded faithfulness judge (role: judge) is phase 3 work."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ItemScore:
    id: str
    kind: str
    citation_validity: float
    path_recall: float
    phrase_hit: bool
    abstain_correct: bool | None
    cited_forbidden: list[str] = field(default_factory=list)
    tool_calls: int = 0
    duration_s: float = 0.0
    error: str | None = None

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        if self.abstain_correct is not None:
            return self.abstain_correct
        return (
            self.path_recall == 1.0 and self.phrase_hit and not self.cited_forbidden and self.citation_validity >= 0.95
        )


def score_item(item: dict[str, Any], record: dict[str, Any]) -> ItemScore:
    answer = record.get("answer") or {}
    cited = {c["path"].lstrip("/") for c in answer.get("citations", [])}
    expect = [p.lstrip("/") for p in item.get("expect_paths", [])]
    recall = 1.0 if not expect else sum(p in cited for p in expect) / len(expect)
    text = (answer.get("answer") or "").lower()
    phrases = item.get("expect_any") or []
    phrase_hit = not phrases or any(p.lower() in text for p in phrases)
    abstain = None
    if "expect_abstain" in item:
        abstain = bool(answer.get("abstained")) == bool(item["expect_abstain"])
    forbidden = sorted(cited & {p.lstrip("/") for p in item.get("must_not_cite", [])})
    return ItemScore(
        id=item["id"],
        kind=item.get("kind", "lookup"),
        citation_validity=record.get("citation_validity") if record.get("citation_validity") is not None else 0.0,
        path_recall=recall,
        phrase_hit=phrase_hit,
        abstain_correct=abstain,
        cited_forbidden=forbidden,
        tool_calls=sum((record.get("tool_calls") or {}).values()),
        duration_s=record.get("duration_s", 0.0),
        error=record.get("error"),
    )


# Release gates (design doc, Evals > metrics). Tune once the golden set is real.
GATES = {"pass_rate": 0.8, "citation_validity": 0.95, "abstain_accuracy": 1.0}


def summarize(scores: list[ItemScore]) -> dict[str, Any]:
    n = len(scores) or 1
    abstain = [s for s in scores if s.abstain_correct is not None]
    summary = {
        "items": len(scores),
        "pass_rate": round(sum(s.passed for s in scores) / n, 3),
        "citation_validity": round(
            sum(s.citation_validity for s in scores if s.abstain_correct is None)
            / max(1, sum(s.abstain_correct is None for s in scores)),
            3,
        ),
        "abstain_accuracy": round(sum(bool(s.abstain_correct) for s in abstain) / len(abstain), 3) if abstain else None,
        "mean_tool_calls": round(sum(s.tool_calls for s in scores) / n, 1),
        "mean_duration_s": round(sum(s.duration_s for s in scores) / n, 2),
        "failed": [s.id for s in scores if not s.passed],
    }
    summary["gates_passed"] = all(summary[k] is None or summary[k] >= v for k, v in GATES.items())
    return summary
