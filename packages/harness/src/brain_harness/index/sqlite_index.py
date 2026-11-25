"""Local index: an accelerator, never the source of truth.

One SQLite file per bundle holds a page table and an FTS5 BM25 index over
title, description, tags and body. It is rebuildable from the bundle at any
time and records the commit it was built from, so stale hits are visible.

Vectors (sqlite-vec over 300-word chunks with 50-word overlap) plug in through
:class:`VectorStore` and are fused with BM25 by page-level reciprocal rank
fusion. Turn ``search`` on only where the eval matrix shows a gain (phase 5).
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from okf import Bundle

_TOKEN = re.compile(r"[\w][\w'-]*", re.UNICODE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS pages (
    path TEXT PRIMARY KEY, type TEXT, title TEXT, description TEXT, tags TEXT, body TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    path UNINDEXED, title, description, tags, body,
    tokenize = "unicode61 remove_diacritics 2 tokenchars '-_/'"
);
"""

# bm25() weights per column: path (unindexed), title, description, tags, body
_WEIGHTS = (0.0, 10.0, 5.0, 3.0, 1.0)


@dataclass(frozen=True)
class Hit:
    path: str
    score: float
    snippet: str


class VectorStore(Protocol):
    """Chunk-embedding store. Implementations return best chunk per page, best first."""

    def search(self, query: str, k: int) -> list[Hit]: ...


def chunk_words(text: str, size: int = 300, overlap: int = 50) -> list[str]:
    """Word chunks for embeddings (gbrain's 300/50 default)."""
    words = text.split()
    if not words:
        return []
    step = max(1, size - overlap)
    return [" ".join(words[i : i + size]) for i in range(0, max(1, len(words) - overlap), step)]


def rrf(
    rankings: Sequence[Sequence[str]], k: int = 60, weights: Sequence[float] | None = None
) -> list[tuple[str, float]]:
    """Page-level reciprocal rank fusion: score = sum(weight / (k + rank))."""
    weights = weights or [1.0] * len(rankings)
    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, weights, strict=True):
        for rank, path in enumerate(ranking, start=1):
            scores[path] = scores.get(path, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def to_fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 query: quoted tokens joined with OR."""
    tokens = [t for t in _TOKEN.findall(text.lower()) if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(tokens))


def git_head(root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


class SqliteIndex:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def rebuild(self, bundle: Bundle) -> int:
        with self.conn:
            self.conn.execute("DELETE FROM pages")
            self.conn.execute("DELETE FROM pages_fts")
            rows = [
                (path, c.type, c.title, c.description or "", " ".join(c.tags), c.body)
                for path, c in bundle.concepts.items()
            ]
            self.conn.executemany("INSERT INTO pages VALUES (?,?,?,?,?,?)", rows)
            self.conn.executemany(
                "INSERT INTO pages_fts (path, title, description, tags, body) VALUES (?,?,?,?,?)",
                [(r[0], r[2], r[3], r[4], r[5]) for r in rows],
            )
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES ('commit', ?)", (git_head(bundle.root) or "",))
        return len(rows)

    @property
    def indexed_commit(self) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key='commit'").fetchone()
        return row[0] or None if row else None

    def bm25(self, query: str, k: int = 20) -> list[Hit]:
        fts = to_fts_query(query)
        if not fts:
            return []
        weights = ", ".join(str(w) for w in _WEIGHTS)
        sql = (
            f"SELECT path, bm25(pages_fts, {weights}) AS score, "
            "snippet(pages_fts, 4, '[', ']', ' … ', 12) "
            "FROM pages_fts WHERE pages_fts MATCH ? ORDER BY score LIMIT ?"
        )
        return [Hit(path=p, score=-s, snippet=snip) for p, s, snip in self.conn.execute(sql, (fts, k))]

    def search(self, query: str, k: int = 20, vectors: VectorStore | None = None) -> list[Hit]:
        """BM25 alone, or BM25 fused with vectors by page-level RRF."""
        keyword = self.bm25(query, k * 2)
        if vectors is None:
            return keyword[:k]
        semantic = vectors.search(query, k * 2)
        fused = rrf([[h.path for h in keyword], [h.path for h in semantic]])
        snippets = {h.path: h.snippet for h in [*semantic, *keyword]}
        return [Hit(path=p, score=s, snippet=snippets.get(p, "")) for p, s in fused[:k]]

    def paths(self) -> Iterable[str]:
        return (row[0] for row in self.conn.execute("SELECT path FROM pages ORDER BY path"))
