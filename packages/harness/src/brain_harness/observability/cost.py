"""Dollar cost of a run, from the provider usage on each model response.

Prices come from Pydantic AI's bundled price table (genai-prices). A model the
table does not know, or a test model, adds nothing, and the result says how
many responses could not be priced so a run is never shown as cheaper than it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Cost:
    usd: float = 0.0
    priced: int = 0
    unpriced: int = 0


def messages_cost(messages: list[Any]) -> Cost:
    from pydantic_ai.messages import ModelResponse

    cost = Cost()
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        try:
            cost.usd += float(message.cost().total_price)
            cost.priced += 1
        except Exception:  # unknown model, missing usage, or a test model
            cost.unpriced += 1
    return cost
