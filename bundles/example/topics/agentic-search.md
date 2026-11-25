---
type: topic
title: Agentic search
description: How agents search with tools instead of a single retrieval step.
tags: [search, ai]
stale_after: 2026-11-01T00:00:00Z
generated:
  by: brain-harness/0.1.0+example
  at: 2026-09-01T08:00:00Z
verified:
  - by: brain-harness/0.1.0+verifier
    at: 2026-09-02T08:00:00Z
x-example-confidence: medium
---
# Agentic search

The model drives tools such as `grep` and `read` in a loop, decides what to open
next, and stops when it can answer. See [OKF search harness](../projects/okf-harness.md).

Harness design changes results as much as the retriever does.
