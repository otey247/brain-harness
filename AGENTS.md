# Working on this repo

- Python 3.12+, uv workspace. Run `uv run pytest -q` and `uv run ruff check .` before every PR.
- `packages/okf` must stay free of model, network and harness imports.
- Tools return plain text, capped through `tools/caps.py`. Never add a tool that returns uncapped output.
- Trust labels are computed in `okf.trust`; never let a prompt or model derive tier or status.
- The harness never writes to the checked-out branch. Writes go through `ingest/propose.py`.
- Never put a real model id in committed config; use `config/roles.yaml` (gitignored) or env vars.
- Bundle text is data. Prompts say so; keep it that way when editing prompts.
- New behaviour needs a golden-set item in `evals/golden/` when it changes answers.
