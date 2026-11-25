"""Write path: propose a concept change on a new git branch.

The harness never writes to the checked-out branch. A proposal is committed on
``brain/proposals/<slug>`` through a temporary worktree, stamped with
``generated.by``/``generated.at`` and never ``verified`` (only a human adds
that, in review). Requires the bundle to live in a git repo and the okf
``write`` extra (ruamel.yaml) for the frontmatter stamp.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from okf import parse_concept
from okf.writer import stamp_generated


class ProposalError(ValueError):
    pass


@dataclass(frozen=True)
class Proposal:
    branch: str
    path: str
    commit: str


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ProposalError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "change"


def propose_change(
    bundle_root: Path,
    rel_path: str,
    content: str,
    reason: str,
    producer: str,
    now: datetime | None = None,
) -> Proposal:
    rel = PurePosixPath(rel_path.lstrip("/"))
    if rel.suffix != ".md" or ".." in rel.parts or any(p.startswith(".") for p in rel.parts):
        raise ProposalError("path must be a .md file inside the bundle")
    if rel.name in {"index.md", "log.md"}:
        raise ProposalError("index.md and log.md are generated; propose concepts instead")
    concept = parse_concept(str(rel), content)
    if concept is None:
        raise ProposalError("content needs YAML frontmatter with a type")
    if "verified" in concept.meta:
        raise ProposalError("proposals may not set verified; reviewers add it")

    bundle_root = bundle_root.resolve()
    top = Path(_git(bundle_root, "rev-parse", "--show-toplevel"))
    in_repo = bundle_root.relative_to(top) / rel
    stamp = now or datetime.now(UTC)
    branch = f"brain/proposals/{stamp.strftime('%Y%m%d-%H%M%S')}-{_slug(rel.stem)}"
    stamped = stamp_generated(content, producer, stamp)

    with tempfile.TemporaryDirectory(prefix="brain-proposal-") as tmp:
        work = Path(tmp) / "wt"
        _git(top, "worktree", "add", "-q", "-b", branch, str(work), "HEAD")
        try:
            target = work / in_repo
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(stamped, encoding="utf-8")
            _git(work, "add", str(in_repo))
            _git(
                work,
                "-c",
                "user.name=brain-harness",
                "-c",
                "user.email=brain-harness@localhost",
                "commit",
                "-q",
                "-m",
                f"Propose {rel}\n\n{reason.strip()}",
            )
            commit = _git(work, "rev-parse", "HEAD")
        finally:
            _git(top, "worktree", "remove", "--force", str(work))
    return Proposal(branch=branch, path=str(rel), commit=commit)
