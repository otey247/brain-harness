"""Live smoke test against a real model. Skipped unless you opt in.

    export ANTHROPIC_API_KEY=...            # or OPENAI_API_KEY, in your shell, never in a file
    BRAIN_LIVE_MODEL=claude:<model id> uv run pytest -m live

It asks the example bundle one question and checks the answer is grounded:
at least one citation, every citation verified at its lines, no abstention.
One run costs a few cents.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

MODEL = os.environ.get("BRAIN_LIVE_MODEL")


@pytest.mark.skipif(not MODEL, reason="set BRAIN_LIVE_MODEL to run live model tests")
def test_live_answer_is_grounded(settings):
    pytest.importorskip("pydantic_ai")
    from brain_harness.agent.loop import Harness
    from brain_harness.config import Roles
    from brain_harness.models.registry import missing_key

    assert MODEL
    if key := missing_key(MODEL):
        pytest.skip(f"{key} is not set")
    settings.roles = Roles.model_validate({"planner": {"model": MODEL}})
    result = Harness(settings).ask_sync("What did we decide about retrieval, and why?")
    answer = result.answer
    print(answer.answer, result.record.usage)
    assert not answer.abstained
    assert answer.citations, "a grounded answer cites the bundle"
    assert result.citations.validity == 1.0, result.citations.invalid
    assert result.record.usage["requests"] >= 1
