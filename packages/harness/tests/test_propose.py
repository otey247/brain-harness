from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("ruamel.yaml")

from brain_harness.ingest.propose import ProposalError, propose_change
from conftest import EXAMPLE, NOW


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(EXAMPLE, root / "bundle")
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "-b", "main")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return root


def test_proposal_lands_on_new_branch_only(repo):
    content = "---\ntype: note\ntitle: New\n---\n# New\n"
    p = propose_change(repo / "bundle", "notes/new.md", content, "test", "brain-harness/test", NOW)
    assert p.branch.startswith("brain/proposals/")
    assert not (repo / "bundle" / "notes" / "new.md").exists()
    shown = subprocess.run(
        ["git", "-C", str(repo), "show", f"{p.branch}:bundle/notes/new.md"], capture_output=True, text=True, check=True
    ).stdout
    assert "generated:" in shown and "brain-harness/test" in shown


@pytest.mark.parametrize(
    "path,content",
    [
        ("../x.md", "---\ntype: note\n---\n"),
        ("index.md", "---\ntype: note\n---\n"),
        ("a.md", "no frontmatter"),
        ("a.md", "---\ntype: note\nverified:\n  - by: human:me\n    at: 2026-01-01T00:00:00Z\n---\n"),
    ],
)
def test_bad_proposals_rejected(repo, path, content):
    with pytest.raises(ProposalError):
        propose_change(repo / "bundle", path, content, "r", "p", NOW)
