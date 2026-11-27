"""Local command for the distributed cited-search workflow."""

import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir

from brain_harness.agent.loop import Harness
from brain_harness.agent.output import Answer
from brain_harness.config import BundleConfig, RoleModel, Roles, Settings
from brain_harness.models.registry import check_allowed, missing_key

RESOURCES = Path(__file__).resolve().parent
PROVIDERS = ("anthropic", "openai")


def live_roles(args: argparse.Namespace, bundle: BundleConfig) -> Roles:
    if not args.question.strip():
        raise ValueError("provide a nonblank question")
    planner = os.getenv("BRAIN_PLANNER_MODEL") or os.getenv("BRAIN_MODEL")
    if not planner:
        raise ValueError("set BRAIN_PLANNER_MODEL or BRAIN_MODEL to provider:model")
    planner_role = RoleModel(model=planner)
    searcher_role = RoleModel(model=os.getenv("BRAIN_SEARCHER_MODEL") or os.getenv("BRAIN_MODEL") or planner)
    for role in (planner_role, searcher_role):
        check_allowed(role, bundle)
        if key := missing_key(role.model):
            raise ValueError(f"set {key} to use the configured provider")
    return Roles(planner=planner_role, searcher=searcher_role)


def check_bundle(root: Path) -> None:
    if not root.is_dir():
        raise ValueError("bundle must be an existing directory")
    # The model may read non-concept files too. Accept plain, operator-owned directory trees.
    for base, dirs, files in root.walk():
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        for name in dirs + files:
            if (base / name).is_symlink():
                raise ValueError("the workflow bundle must contain regular files and directories without symlinks")
        for name in files:
            if not name.startswith(".") and not (base / name).is_file():
                raise ValueError("special files are not supported in the bundle")


def execute(args: argparse.Namespace) -> Answer:
    live = args.command == "ask"
    root = (args.bundle if live and args.bundle else RESOURCES / "bundle").resolve()
    policy = BundleConfig(path=root, allowed_providers=args.allow_provider if live else [])
    roles = live_roles(args, policy) if live else Roles(planner=RoleModel(model="test"))
    if Path(gettempdir()).resolve().is_relative_to(root):
        raise ValueError("temporary directory must be outside the bundle")
    check_bundle(root)
    with TemporaryDirectory(prefix="cited-search-") as directory:
        tmp = Path(directory).resolve()
        logs = args.log_dir.resolve() if args.log_dir else tmp / "runs"
        if logs.is_relative_to(root):
            raise ValueError("scratch and log directories must be outside the bundle")
        settings = Settings(
            bundles={"knowledge": policy},
            default_bundle="knowledge",
            roles=roles,
            scratch_dir=tmp / "scratch",
            run_log_dir=logs,
        )
        harness = Harness(settings)
        if not harness.bundle.concepts:
            raise ValueError("bundle contains no OKF concepts")
        if args.log_dir:
            logs.mkdir(mode=0o700, parents=True, exist_ok=True)
        if live:
            return harness.ask_sync(args.question).answer
        from brain_harness.workflows.cited_search.smoke import run

        return run(harness).answer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cited-search", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("manifest", help="print the installed distribution manifest")
    commands.add_parser("schema", help="print the output JSON Schema")
    smoke = commands.add_parser("smoke", help="check the installed workflow offline")
    ask = commands.add_parser("ask", help="ask a live model to search a bundle")
    ask.add_argument("question")
    ask.add_argument("--live", action="store_true", required=True)
    ask.add_argument("--allow-provider", choices=PROVIDERS, action="append", required=True)
    ask.add_argument("--bundle", type=Path, help="trusted OKF directory (default: installed example)")
    for cmd in (smoke, ask):
        cmd.add_argument("--log-dir", type=Path, help="retain JSONL run history in this private directory")
    args = parser.parse_args(argv)
    if args.command == "manifest":
        print((RESOURCES / "manifest.json").read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "schema":
        print(json.dumps(Answer.model_json_schema(), indent=2))
        return 0
    try:
        answer = execute(args)
    except (ValueError, OSError) as exc:
        print(f"cited-search: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"cited-search: workflow failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(answer.model_dump_json(indent=2))
    return 0
