# Cited search 0.1.0

Install this kit to run a local knowledge-search workflow. It contains the two project wheels, the locked dependency wheels for the builder's Python and platform, and a fictional Harbor Dispatch knowledge bundle. Both commands use the existing planner, read tools, citation checker and run recorder. Only the live command uses a model provider.

## Install the kit

Extract the ZIP and open a shell inside its top-level directory, next to `requirements.txt`. Use a matching CPython minor version, operating system and architecture, with a compatible native runtime (the supplied Linux x86_64 kit uses manylinux wheels requiring up to glibc 2.34). The filename identifies the build target. Run these commands in a Unix shell.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip --disable-pip-version-check install --no-index --find-links wheels --only-binary=:all: --require-hashes -r requirements.txt
python -m pip check
cited-search smoke
```

For a kit built on Windows, create the environment with `py -3.12 -m venv .venv` and activate it with `.venv\Scripts\Activate.ps1` in PowerShell. The pip and workflow commands are the same. The application works from any directory. Installation and the synthetic smoke run need no index, API keys, Git checkout, external agent host or running service. Ripgrep is optional. The harness has a Python search implementation.

## Run a question against your own knowledge

Use a dedicated OKF v0.3 directory containing only material the chosen provider may see. A concept is a Markdown file with a YAML frontmatter `type`. `cited-search ask` uses the installed example when `--bundle` is omitted. The following example uses a POSIX shell. Substitute your provider's model ID and supply its API key through the process environment.

```sh
export BRAIN_MODEL='claude:<your-model-id>'
# Set ANTHROPIC_API_KEY through your shell or secret manager.
cited-search ask --live --allow-provider anthropic --bundle /absolute/path/to/notes 'What did we decide about retrieval?'
```

The baseline model comes from `BRAIN_MODEL`. `BRAIN_PLANNER_MODEL` and `BRAIN_SEARCHER_MODEL` override their respective roles. If only the planner is set, the searcher inherits it. The other supported provider is `openai` with `OPENAI_API_KEY`. Repeat `--allow-provider` to permit both for a mixed-role run. The CLI checks both roles before constructing either provider client. This profile takes the bundle and provider permissions from its arguments. Repository config files, dotenv files and `BRAIN_BUNDLE` do not configure it.

The caller owns the local process and must trust its environment, including provider SDK endpoint overrides, proxies and the executable search path. The allowlist checks provider names. Use OS/network controls when a particular destination must be enforced. The live provider can receive the question, tool outputs and bundle content. Budget, caching and usage accounting follow the harness defaults. A dollar budget is not a billing ceiling.

## Inputs, outputs and storage

| Command | Input | Standard output on success |
| --- | --- | --- |
| `cited-search manifest` | None | Installed manifest with workflow and contract versions |
| `cited-search schema` | None | JSON Schema generated from the harness's typed Answer |
| `cited-search smoke` | Fixed question over the installed bundle | Answer JSON with a checked citation for the 18:30 UTC handoff |
| `cited-search ask --live --allow-provider … 'question'` | One nonblank positional question, optional `--bundle DIR` | Answer JSON |

`answer` is the response text. Each item in `citations` has a bundle-relative `path`, 1-based inclusive `start_line` and `end_line`, a `quote`, and the associated `claim`. Verification checks normalized quote text near the reported lines (two lines of tolerance). It does not assess whether every claim follows from that quote. `concepts_used` carries computed trust, status and staleness. Consumers should inspect `gaps` and `abstained`. Unsupported citations are removed and recorded as gaps. A completed live run, including an abstention, exits 0. Command-line usage errors exit 2. Execution and configuration errors exit 1 and write a diagnostic to standard error.

The synthetic smoke model follows a fixed grep/read sequence. It must find and open the installed procedure, return its actual numbered line through the typed agent loop, and pass the citation check. It exercises packaging and workflow execution. It does not measure live model quality.

The workflow has read-only bundle tools and no proposal, shell or HTTP command. Use a stable directory tree of regular files without symlinks. Read tools can open assets as well as Markdown, so keep credentials, unrelated documents and logs outside the bundle. Scratch spills and run logs go into a private temporary directory and are removed on normal exit. To retain questions, answers, evidence paths, usage, cost and errors, pass `--log-dir DIR` to either run command. Use a private directory with appropriate filesystem permissions and retention. This is a single-user process with the caller's OS permissions.

## Build and verify from source

From the repository root, use CPython 3.12 with pip and uv 0.13.9 (the verified builder). Building fetches artifacts from PyPI. The committed uv.lock fixes runtime and build dependency versions and artifact hashes. The builder uses both workspace packages directly, verifies downloaded hashes, takes only binary wheels, and writes an install-time hash for each wheel. Build on the consumer's platform. If a pinned binary wheel is unavailable, the build fails.

```sh
python3.12 distribution/cited-search/build.py
python3.12 distribution/cited-search/verify.py dist/cited-search-0.1.0-cpython-312-linux-x86_64.zip
```

Use the filename printed by the builder for your platform. The verifier installs the ZIP into a new environment outside the checkout. The fixed archive order, timestamps, permissions and build backend permit comparing two builds on the same target and toolchain. Digests check integrity against an already trusted kit. They do not authenticate its origin.

## Why Python first

| | Python wheel kit (implemented) | OCI image |
| --- | --- | --- |
| Consumer prerequisite | Matching CPython with venv and pip | Container runtime, compatible image architecture |
| Offline handoff | Transfer one ZIP and install its hashed wheels | Transfer a saved image and load it locally |
| Bundle and logs | Pass local paths under caller permissions | Read-only bundle mount, optional writable log mount |
| Runtime isolation | Virtual environment isolates dependencies. OS user controls access. | Image can pin the interpreter and OS libraries, run as a non-root UID, and restrict mounts and networking |
| HTTP | CLI opens no listener | CLI also needs no port. Publishing the existing API would require a separate access-control design. |

The two Python packages already expose the workflow in-process. A local wheel kit gives CLI users the shortest installation path and avoids introducing an image build, registry or network service. An OCI image would make sense for teams that already manage container runtimes or need to control the operating-system layer. The repository's existing API has one configured harness and no caller authentication. This kit does not start it.
