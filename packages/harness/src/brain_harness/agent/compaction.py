"""Context budgeting as a Pydantic AI history processor.

Order of operations (cheapest and most lossless first):
1. Collapse tool output older than ``collapse_after_turns`` model turns to a
   one-line stub that keeps the tool name and arguments; the agent can re-run it.
2. When the estimate still passes ``compact_at_fraction`` of the window, drop the
   oldest turns after the first request, keeping the question and recent work.
   (A summarising pass can replace step 2; see docs/adr/0003-compaction.md.)

The transforms work on Pydantic AI's message classes but import them lazily, so
this module loads without the dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from brain_harness.tools.caps import estimate_tokens

COLLAPSED = "[collapsed: output of an earlier {tool} call; re-run it if you need it again]"


def _message_tokens(message: Any) -> int:
    total = 0
    for part in getattr(message, "parts", []):
        content = getattr(part, "content", None)
        if content is None:
            content = getattr(part, "args", "")
        total += estimate_tokens(content if isinstance(content, str) else str(content))
    return total


def make_history_processor(
    context_window_tokens: int,
    collapse_after_turns: int = 3,
    compact_at_fraction: float = 0.7,
) -> Callable[[list[Any]], list[Any]]:
    def process(messages: list[Any]) -> list[Any]:
        from dataclasses import replace

        from pydantic_ai.messages import ModelRequest, ModelResponse, ToolReturnPart

        response_idx = [i for i, m in enumerate(messages) if isinstance(m, ModelResponse)]
        cutoff = response_idx[-collapse_after_turns] if len(response_idx) >= collapse_after_turns else -1
        out: list[Any] = []
        for i, message in enumerate(messages):
            if i < cutoff and isinstance(message, ModelRequest):
                parts = [
                    replace(p, content=COLLAPSED.format(tool=p.tool_name)) if isinstance(p, ToolReturnPart) else p
                    for p in message.parts
                ]
                message = replace(message, parts=parts)
            out.append(message)

        budget = int(context_window_tokens * compact_at_fraction)
        while sum(_message_tokens(m) for m in out) > budget and len(out) > 4:
            # keep the first request (system + question); drop the oldest response/request pair
            del out[1:3]
        return out

    return process
