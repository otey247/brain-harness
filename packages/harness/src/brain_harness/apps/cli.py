"""``brain`` command line.

brain ask "What did we decide about retrieval?"
brain tools grep "grep first"          # run one primitive, no model
brain index build                      # (re)build the optional local index
brain mcp [--transport streamable-http]
brain serve [--port 8000]
brain eval [--golden evals/golden/example.yaml]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from brain_harness.config import load_settings


def _harness(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    from brain_harness.agent.loop import Harness

    settings = load_settings(args.config)
    index = settings.scratch_dir.parent / "index.sqlite" if args.index else None
    return Harness(settings, bundle_name=args.bundle, index_path=index)


def cmd_ask(args: argparse.Namespace) -> int:
    from brain_harness.observability.tracing import setup_tracing

    setup_tracing()
    result = _harness(args).ask_sync(args.question)
    if args.json:
        print(result.answer.model_dump_json(indent=2))
        return 0
    a = result.answer
    print(a.answer)
    for c in a.citations:
        print(f"  [{c.path}:{c.start_line}-{c.end_line}] {c.quote}")
    for g in a.gaps:
        print(f"  gap: {g}")
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    from brain_harness.tools.knowledge import ToolError

    tools = _harness(args).tools()
    kwargs = json.loads(args.kwargs) if args.kwargs else {}
    if args.arg is not None:
        first = {
            "grep": "pattern",
            "read": "path",
            "list": "directory",
            "glob": "pattern",
            "links": "path",
            "search": "query",
        }.get(args.name)
        if first:
            kwargs[first] = args.arg
    try:
        print(getattr(tools, args.name)(**kwargs))
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    h = _harness(argparse.Namespace(**{**vars(args), "index": True}))
    count = h.index.rebuild(h.bundle)
    print(f"indexed {count} concepts at commit {h.index.indexed_commit or 'unknown'}")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from brain_harness.apps.mcp_server import build_server
    from brain_harness.observability.tracing import setup_tracing

    setup_tracing()
    build_server(_harness(args)).run(transport=args.transport)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from brain_harness.apps.api import create_app

    uvicorn.run(create_app(_harness(args)), host=args.host, port=args.port)
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path.cwd()))
    from evals.runner import run_golden

    summary = run_golden(_harness(args), Path(args.golden), Path(args.out))
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("gates_passed", False) else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brain", description="Agentic search over OKF bundles")
    parser.add_argument("--config", default=None, help="config directory (default: ./config or BRAIN_CONFIG_DIR)")
    parser.add_argument("--bundle", default=None, help="bundle name from bundles.yaml")
    parser.add_argument("--index", action="store_true", help="attach the local index and enable search")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ask", help="answer a question with citations")
    p.add_argument("question")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("tools", help="run one read tool without a model")
    p.add_argument("name", choices=["list", "glob", "grep", "read", "frontmatter_query", "links", "search"])
    p.add_argument("arg", nargs="?")
    p.add_argument("--kwargs", help="extra arguments as JSON")
    p.set_defaults(func=cmd_tools)

    p = sub.add_parser("index", help="build the local FTS index")
    p.add_argument("action", choices=["build"])
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("mcp", help="run the MCP server")
    p.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("serve", help="run the HTTP API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("eval", help="run the golden set")
    p.add_argument("--golden", default="evals/golden/example.yaml")
    p.add_argument("--out", default=".brain/evals")
    p.set_defaults(func=cmd_eval)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
