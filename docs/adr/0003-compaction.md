# 0003: Context budgeting

Status: accepted (step 2 may change)

Before each model request: (1) tool output older than 3 model turns collapses to a stub naming the tool, which the agent can re-run; (2) above 70% of the context window, the oldest turns after the question are dropped.

Next: replace (2) with a summarising pass that keeps the evidence ledger (paths and line ranges read), then run a probe pass that checks the summary still answers the question. Gate on the golden set.
