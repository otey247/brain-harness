"""End-to-end loop with Pydantic AI's TestModel: no network, no API key."""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic_ai")

from brain_harness.agent.loop import Harness
from conftest import NOW
from pydantic_ai.models.test import TestModel


def test_loop_runs_and_logs(settings):
    harness = Harness(settings, now=NOW)
    model = TestModel(call_tools=["grep", "read"])
    agent = harness.planner()
    with agent.override(model=model), harness.searcher().override(model=model):
        result = harness.ask_sync("What is our retrieval approach?")
    assert result.record.tool_calls
    assert list(settings.run_log_dir.glob("*.jsonl"))
