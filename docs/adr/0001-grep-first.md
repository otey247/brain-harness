# 0001: Grep first, index only on evidence

Status: accepted

The agent starts with file tools (list, glob, grep, read, links) over the Markdown. A BM25 index and vectors exist in `index/` but are off until the golden-set matrix shows a gain for a given bundle and model.

Why: in the grep paper's setup, inline grep beat vector retrieval across all ten harness and model pairs, and harness design moved results as much as the retriever. File tools also keep answers traceable to lines in git.

Consequence: tool output must be capped and trust-labelled, and evals must run retriever x model x delivery mode before turning `search` on.
