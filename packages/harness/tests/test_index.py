from __future__ import annotations

from brain_harness.index.sqlite_index import SqliteIndex, chunk_words, rrf, to_fts_query
from brain_harness.tools.knowledge import KnowledgeTools
from conftest import NOW


def test_bm25_ranks_title_match_first(bundle, tmp_path):
    index = SqliteIndex(tmp_path / "i.sqlite")
    assert index.rebuild(bundle) == len(bundle.concepts)
    hits = index.search("grep first retrieval", k=3)
    assert hits[0].path == "decisions/2026-11-retrieval-grep-first.md"


def test_search_tool_uses_index(bundle, tmp_path):
    index = SqliteIndex(tmp_path / "i.sqlite")
    index.rebuild(bundle)
    out = KnowledgeTools(bundle, now=NOW, index=index).search("Alex Chen")
    assert out.splitlines()[0].startswith("people/alex-chen.md")


def test_fts_query_is_safe():
    assert to_fts_query('drop" OR 1=1; --') == '"drop" OR "or"'
    assert to_fts_query("") == ""


def test_rrf_and_chunks():
    fused = rrf([["a", "b"], ["b", "c"]])
    assert fused[0][0] == "b"
    chunks = chunk_words(" ".join(str(i) for i in range(700)), 300, 50)
    assert len(chunks) == 3 and chunks[1].split()[0] == "250"
