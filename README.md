# brain-harness

A model-agnostic agentic search harness over Open Knowledge Format (OKF) v0.3 bundles: plain Markdown with YAML frontmatter, in git.

The agent searches the way coding agents do (list, grep, read, follow links) instead of a single retrieval step, and every answer comes back with citations that are checked against the files in code. Any model Pydantic AI supports can drive it, and any MCP client can use it as a tool.

Design: *Agentic Search Harness Design* (Claude Doc). This repo is the phase 1 and 2 scaffold.

## Layout

```
packages/okf/        OKF v0.3 library: parse, trust tiers, staleness, links, validator, writer, `okf` CLI
packages/harness/    brain_harness: tools, agent loop, citations check, index, MCP server, CLI, API
  src/brain_harness/
    tools/           list, glob, grep, read, frontmatter_query, links, search (capped, trust-labelled)
    agent/           loop (planner + searcher subagents), guards, compaction, citations, prompts
    models/          role -> model resolution, fallbacks, per-bundle provider allowlist
    index/           optional SQLite FTS5 index (+ vector fusion hook), off by default
    ingest/          propose_change: writes go to a new git branch for review
    observability/   JSONL run log, OpenTelemetry setup
    apps/            mcp_server, cli (`brain`), api (FastAPI)
bundles/example/     small OKF bundle used by tests and the golden set
evals/               golden set, scorers, runner
config/              bundles, roles (example), budgets
docs/adr/            decisions behind the design
```

## Quick start

```bash
uv sync --all-packages --group dev            # add --all-extras for api, otel, vectors, write
cp config/roles.example.yaml config/roles.yaml # set real model ids, or use BRAIN_*_MODEL env vars
cp .env.example .env                           # provider keys

uv run okf validate bundles/example --strict
uv run brain tools grep "grep first"           # one primitive, no model
uv run brain ask "What is our current approach to retrieval?"
uv run brain mcp                               # stdio MCP server
uv run brain serve                             # HTTP API (api extra)
uv run brain eval                              # golden set -> .brain/evals
uv run pytest -q
```

Point it at your own notes with `BRAIN_BUNDLE=/path/to/bundle` or an entry in `config/bundles.yaml`.

### Use it from an MCP client

```json
{
  "mcpServers": {
    "brain": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/brain-harness", "brain", "mcp"],
      "env": { "BRAIN_BUNDLE": "/path/to/bundle" }
    }
  }
}
```

Tools: `ask` (full loop, cited answer), `grep`, `read`, `list`, `links`, `frontmatter_query`, plus `search` when the index is on and `propose` when the bundle has `writes_enabled`.

## How a question is answered

1. The planner orients (`list`), finds (`grep`, `frontmatter_query`, `links`) and reads the lines it will cite. Independent parts go to read-only searcher subagents (`delegate`, up to 6 at once, depth 1).
2. Every tool result is capped (100 matches, 2,000 lines, ~10k tokens). Over the cap, head and tail stay inline and the full text is saved as a `scratch:` file the agent can grep.
3. Every hit carries its trust label (tier, status, stale, superseded-by) computed in code. Conflicts resolve by status, then tier, then freshness, then date.
4. The run must end in a typed `Answer`. Each citation's quote is checked against the cited lines; failures are dropped and listed as gaps, and the tier and status shown come from code.
5. Budgets (requests, tool calls, tokens, cost), repeat-call detection and history compaction are enforced by the harness, not the prompt. One JSON line per run goes to `.brain/runs`.

## Status

| Area | State |
| --- | --- |
| OKF library, validator, writer | Done, tested |
| Tools, caps, spill, trust labels | Done, tested |
| Local FTS index | Done, tested; off by default |
| Citation check, guards | Done, tested |
| MCP server | Done, tested (read tools) |
| Agent loop, subagents, compaction | Written; test runs with Pydantic AI's `TestModel` once deps are installed |
| Proposals on git branches | Written; tests need the `write` extra |
| Evals | Scorers and runner done; golden set has 5 starter items |
| Vectors, ingestion, judge | Phase 3-5 (see the design doc) |
