from __future__ import annotations

from brain_harness.agent.citations import check_citation, verify_answer
from brain_harness.agent.guards import BudgetExceeded, RunGuard
from brain_harness.agent.output import Answer, Citation
from conftest import NOW

GOOD = Citation(
    path="decisions/2026-11-retrieval-grep-first.md",
    start_line=21,
    end_line=21,
    quote="A vector index is added only when the golden-set eval shows a gain.",
    claim="Vectors come only after an eval gain.",
)


def test_valid_citation_passes(bundle):
    assert check_citation(bundle, GOOD) is None


def test_off_by_one_is_tolerated(bundle):
    assert check_citation(bundle, GOOD.model_copy(update={"start_line": 22, "end_line": 22})) is None


def test_fabricated_quote_fails(bundle):
    bad = GOOD.model_copy(update={"quote": "We always use vectors."})
    assert check_citation(bundle, bad) == "quote not found at those lines"


def test_unknown_path_fails(bundle):
    assert check_citation(bundle, GOOD.model_copy(update={"path": "nope.md"})) == "not a concept in this bundle"


def test_verify_answer_drops_bad_and_labels_from_code(bundle):
    bad = GOOD.model_copy(update={"quote": "invented"})
    answer = Answer(answer="Grep first.", citations=[GOOD, bad])
    checked, report = verify_answer(bundle, answer, NOW)
    assert checked.citations == [GOOD]
    assert report.validity == 0.5
    assert checked.concepts_used[0].tier == "human-reviewed"
    assert any("Unsupported citation removed" in g for g in checked.gaps)


def test_guard_nudges_on_repeats_and_caps_calls():
    guard = RunGuard(repeat_call_limit=2, max_tool_calls=5)
    assert guard.check("grep", {"pattern": "x"}) is None
    assert guard.check("grep", {"pattern": "x"}) is None
    assert "already ran grep" in (guard.check("grep", {"pattern": "x"}) or "")
    guard.check("read", {"path": "a"})
    guard.check("read", {"path": "b"})
    try:
        guard.check("read", {"path": "c"})
    except BudgetExceeded:
        pass
    else:
        raise AssertionError("expected BudgetExceeded")
