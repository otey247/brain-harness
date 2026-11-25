---
type: decision
title: "Retrieval: grep first"
description: Start with grep-style tools; add BM25 and vectors only when evals show a gain.
tags: [search, retrieval]
status: stable
sources:
  - id: paper
    resource: https://arxiv.org/abs/2605.15184
    title: "Is Grep All You Need? How Agent Harnesses Reshape Agentic Search"
generated:
  by: brain-harness/0.1.0+example
  at: 2026-11-22T10:00:00Z
verified:
  - by: human:owner
    at: 2026-11-22T18:30:00Z
---
# Retrieval: grep first

We start with list, glob, grep and read tools over the markdown. In the paper's
setup, inline grep beat vector retrieval in all ten harness and model pairs.[^paper]

A vector index is added only when the golden-set eval shows a gain.

This replaces [the earlier vectors-first plan](2026-06-retrieval-vectors-first.md).
