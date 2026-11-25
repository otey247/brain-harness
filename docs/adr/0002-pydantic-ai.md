# 0002: Pydantic AI for the model layer, harness owns the loop

Status: accepted

Models are `provider:model` strings per role (planner, searcher, writer, judge) with fallbacks, resolved by Pydantic AI. A LiteLLM proxy is optional for one gateway.

Why: typed outputs, tool schemas from signatures, usage limits, OTel instrumentation and a no-network `TestModel`, without a framework that owns the control flow. Budgets, stuck detection, compaction and the citation check stay in this repo so they work the same on every provider.
