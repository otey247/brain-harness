---
type: project
title: OKF search harness
description: Building a model-agnostic agentic search harness over this bundle.
tags: [ai, search, okf]
status: stable
sources:
  - id: design
    resource: https://example.com/design-doc
    title: Agentic Search Harness Design
generated:
  by: brain-harness/0.1.0+example
  at: 2026-11-20T15:00:00Z
verified:
  - by: human:owner
    at: 2026-11-21T09:00:00Z
---
# OKF search harness

The harness searches this bundle with file tools first and adds an index only
when evals show a gain.[^design] The retrieval decision is recorded in
[Retrieval: grep first](../decisions/2026-11-retrieval-grep-first.md).

Owner: [Alex Chen](/people/alex-chen.md).

## Milestones

- Phase 1: OKF package and golden set.
- Phase 2: grep harness with citations.

[^design]: Agentic Search Harness Design, section Recommendations.
