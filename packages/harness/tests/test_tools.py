from __future__ import annotations

from pathlib import Path

import pytest
from brain_harness.config import Caps
from brain_harness.tools.caps import cap_output
from brain_harness.tools.knowledge import KnowledgeTools, ToolError
from conftest import NOW


@pytest.fixture
def tools(bundle, tmp_path: Path) -> KnowledgeTools:
    return KnowledgeTools(bundle, scratch_dir=tmp_path / "scratch", now=NOW)


def test_list_root_shows_description_and_dirs(tools):
    out = tools.list()
    assert "Example knowledge bundle" in out
    assert "decisions/" in out


def test_grep_content_carries_labels_and_line_numbers(tools):
    out = tools.grep("inline grep", mode="content")
    assert "== decisions/2026-11-retrieval-grep-first.md" in out
    assert "human-reviewed" in out
    assert any(line.split(":", 1)[0].strip().isdigit() for line in out.splitlines() if not line.startswith("=="))
    assert "decisions/2026-11-retrieval-grep-first.md" in tools.ledger.grep_hits


def test_grep_files_mode_marks_deprecated(tools):
    out = tools.grep("vector", mode="files")
    assert "deprecated, superseded by /decisions/2026-11-retrieval-grep-first.md" in out


def test_grep_rejects_bad_regex(tools):
    with pytest.raises(ToolError):
        tools.grep("(unclosed")


def test_read_uses_file_line_numbers_and_records(tools):
    out = tools.read("decisions/2026-11-retrieval-grep-first.md", offset=18, limit=3)
    assert out.splitlines()[1].startswith("18")
    assert ("decisions/2026-11-retrieval-grep-first.md", 18, 20) in [
        (p, *r) for p, rs in tools.ledger.reads.items() for r in rs
    ]


def test_read_deprecated_points_to_successor(tools):
    out = tools.read("decisions/2026-06-retrieval-vectors-first.md")
    assert "2026-11-retrieval-grep-first.md" in out.splitlines()[0] + out.splitlines()[1]


@pytest.mark.parametrize("path", ["../README.md", "/../../etc/passwd", ".git/config"])
def test_paths_cannot_escape(tools, path):
    with pytest.raises(ToolError):
        tools.read(path)


def test_frontmatter_query_filters(tools):
    assert "agentic-search" in tools.frontmatter_query(stale=True)
    out = tools.frontmatter_query(tier="human-reviewed")
    assert "okf-harness" in out and "vectors-first" not in out
    assert "vectors-first" in tools.frontmatter_query(status="deprecated")


def test_links_both_directions(tools):
    out = tools.links("projects/okf-harness.md")
    assert "-> people/alex-chen.md" in out
    assert "<- topics/agentic-search.md" in out


def test_search_disabled_without_index(tools):
    with pytest.raises(ToolError, match="not enabled"):
        tools.search("grep")


def test_cap_spills_and_keeps_head_and_tail(tmp_path):
    text = "\n".join(f"line {i}" for i in range(5000))
    capped = cap_output(text, max_tokens=200, spill_dir=tmp_path, label="t")
    assert capped.truncated and capped.spill_path and capped.spill_path.startswith("scratch:")
    assert capped.text.startswith("line 0") and capped.text.rstrip().endswith("line 4999")
    assert (tmp_path / capped.spill_path.removeprefix("scratch:")).read_text() == text


def test_spilled_output_is_readable_through_tools(bundle, tmp_path):
    tools = KnowledgeTools(bundle, caps=Caps(tool_output_tokens=50), scratch_dir=tmp_path, now=NOW)
    out = tools.grep(".", mode="content")
    assert "scratch:" in out
    spill = out.split("saved as ", 1)[1].split(";", 1)[0]
    assert "line" in tools.read(spill) or tools.read(spill)
