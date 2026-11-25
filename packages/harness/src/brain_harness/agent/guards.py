"""Loop guards the harness enforces in code, not in the prompt.

Budgets on requests, tool calls and tokens map onto Pydantic AI ``UsageLimits``.
What usage limits cannot see is a model stuck repeating itself, so the guard
counts identical tool calls and, past the limit, returns a nudge instead of
running the tool again. Cost is tracked from provider usage after each run.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


class BudgetExceeded(RuntimeError):
    """Raised when a run passes a hard budget the provider usage cannot cap."""


def call_key(tool: str, args: dict[str, Any]) -> str:
    return f"{tool}:{json.dumps(args, sort_keys=True, default=str)}"


@dataclass
class RunGuard:
    repeat_call_limit: int = 3
    max_tool_calls: int = 150
    max_cost_usd: float | None = None
    calls: Counter[str] = field(default_factory=Counter)
    tool_calls: int = 0
    cost_usd: float = 0.0

    def check(self, tool: str, args: dict[str, Any]) -> str | None:
        """Record a call. Return a nudge when the call should not run, else None."""
        self.tool_calls += 1
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExceeded(f"tool call budget of {self.max_tool_calls} reached")
        key = call_key(tool, args)
        self.calls[key] += 1
        if self.calls[key] > self.repeat_call_limit:
            return (
                f"You already ran {tool} with these exact arguments {self.calls[key] - 1} times. "
                "Change the query, read a different range, or return the Answer with what you have."
            )
        return None

    def add_cost(self, usd: float) -> None:
        self.cost_usd += usd
        if self.max_cost_usd is not None and self.cost_usd > self.max_cost_usd:
            raise BudgetExceeded(f"cost budget of ${self.max_cost_usd:.2f} reached (${self.cost_usd:.2f})")
