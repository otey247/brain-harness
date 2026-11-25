"""``okf`` command: validate a bundle or scan it by frontmatter.

``scan`` mirrors the filters of okf-consume's ``scripts/scan.py``: type, tag,
grep, current, stale, deprecated, unverified, with ``--json`` output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime

from okf.bundle import Bundle
from okf.model import Status, TrustTier
from okf.trust import trust_info
from okf.validate import Severity, is_conformant, validate


def _scan(args: argparse.Namespace) -> int:
    bundle = Bundle.load(args.bundle)
    now = datetime.now(UTC)
    pattern = re.compile(args.grep, re.IGNORECASE) if args.grep else None
    rows = []
    for path, concept in sorted(bundle.concepts.items()):
        info = trust_info(concept, now)
        if args.type and concept.type != args.type:
            continue
        if args.tag and args.tag not in concept.tags:
            continue
        if args.current and info.status in (Status.DEPRECATED, Status.UNKNOWN):
            continue
        if args.stale and not info.stale:
            continue
        if args.deprecated and info.status is not Status.DEPRECATED:
            continue
        if args.unverified and info.tier is not TrustTier.UNVERIFIED:
            continue
        if pattern and not (pattern.search(concept.body) or pattern.search(concept.title)):
            continue
        rows.append(
            {
                "path": path,
                "type": concept.type,
                "title": concept.title,
                "description": concept.description,
                **info.as_dict(),
            }
        )
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for row in rows:
            print(
                f"{row['path']}\t{row['type']}\t{row['tier']}\t{row['status']}"
                + ("\tstale" if row["stale"] else "")
                + f"\t{row['title']}"
            )
    return 0


def _validate(args: argparse.Namespace) -> int:
    issues = validate(Bundle.load(args.bundle))
    if args.json:
        json.dump([i.__dict__ | {"severity": i.severity.value} for i in issues], sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for issue in issues:
            print(issue)
    if not is_conformant(issues):
        return 1
    if args.strict and any(i.severity is Severity.WARNING for i in issues):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="okf")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="list concepts filtered by frontmatter")
    scan.add_argument("bundle")
    scan.add_argument("--type")
    scan.add_argument("--tag")
    scan.add_argument("--grep")
    scan.add_argument("--current", action="store_true")
    scan.add_argument("--stale", action="store_true")
    scan.add_argument("--deprecated", action="store_true")
    scan.add_argument("--unverified", action="store_true")
    scan.add_argument("--json", action="store_true")
    scan.set_defaults(func=_scan)

    val = sub.add_parser("validate", help="check conformance and quality")
    val.add_argument("bundle")
    val.add_argument("--strict", action="store_true", help="exit 2 on warnings")
    val.add_argument("--json", action="store_true")
    val.set_defaults(func=_validate)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
