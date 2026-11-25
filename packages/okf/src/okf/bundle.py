"""Reading an OKF bundle from disk (SPEC §3, §4, §8).

A bundle is a directory. Every ``.md`` file whose frontmatter has a ``type`` is a
concept; other ``.md`` files (README, AGENTS, SKILL) are skipped; non-``.md``
files are assets. Dot-paths are excluded and symlinks that leave the bundle are
not followed. ``index.md`` and ``log.md`` are reserved at any level.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from okf.links import Link, extract_links, path_field_edges
from okf.model import Concept, is_empty
from okf.yaml12 import Yaml12Error, load_mapping

RESERVED = frozenset({"index.md", "log.md"})


@dataclass(frozen=True)
class ParseIssue:
    path: str
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class Frontmatter:
    meta: dict[str, Any]
    body: str
    body_start_line: int
    has_frontmatter: bool


def split_frontmatter(text: str) -> Frontmatter:
    """Split ``---``-delimited frontmatter from the body.

    The file must *start* with ``---`` for frontmatter to exist (SPEC §4.1).
    Raises Yaml12Error when the block is present but invalid.
    """
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return Frontmatter(meta={}, body=text, body_start_line=1, has_frontmatter=False)
    for idx in range(1, len(lines)):
        if lines[idx].rstrip("\r\n") in ("---", "..."):
            meta = load_mapping("".join(lines[1:idx]))
            return Frontmatter(
                meta=meta,
                body="".join(lines[idx + 1 :]),
                body_start_line=idx + 2,
                has_frontmatter=True,
            )
    raise Yaml12Error("frontmatter opened with --- but never closed")


def parse_concept(path: str, text: str) -> Concept | None:
    """Parse one file. Returns None when it is not a concept (no ``type``)."""
    fm = split_frontmatter(text)
    if is_empty(fm.meta.get("type")):
        return None
    return Concept(path=path, meta=fm.meta, body=fm.body, body_start_line=fm.body_start_line, raw=text)


@dataclass
class Bundle:
    root: Path
    concepts: dict[str, Concept] = field(default_factory=dict)
    assets: list[str] = field(default_factory=list)
    other_markdown: list[str] = field(default_factory=list)
    reserved: list[str] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    root_index_meta: dict[str, Any] = field(default_factory=dict)

    # ---- loading -------------------------------------------------------
    @classmethod
    def load(cls, root: str | os.PathLike[str]) -> Bundle:
        bundle = cls(root=Path(root).resolve())
        bundle._scan()
        return bundle

    def _scan(self) -> None:
        for rel in sorted(iter_bundle_files(self.root)):
            name = rel.rsplit("/", 1)[-1]
            if not rel.endswith(".md"):
                self.assets.append(rel)
                continue
            text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            if name in RESERVED:
                self.reserved.append(rel)
                if rel == "index.md":
                    try:
                        self.root_index_meta = split_frontmatter(text).meta
                    except Yaml12Error as exc:
                        self.issues.append(ParseIssue(rel, 1, "E101", f"invalid frontmatter: {exc}"))
                continue
            try:
                concept = parse_concept(rel, text)
            except Yaml12Error as exc:
                self.issues.append(ParseIssue(rel, 1, "E101", f"invalid frontmatter: {exc}"))
                continue
            if concept is None:
                self.other_markdown.append(rel)
            else:
                self.concepts[rel] = concept

    # ---- queries -------------------------------------------------------
    @property
    def description(self) -> str | None:
        value = self.root_index_meta.get("description")
        return None if is_empty(value) else str(value)

    @property
    def okf_version(self) -> str | None:
        value = self.root_index_meta.get("okf_version")
        return None if is_empty(value) else str(value)

    def exists(self, rel: str) -> bool:
        return rel in self.concepts or rel in self.assets or rel in self.reserved

    def get(self, rel: str) -> Concept | None:
        return self.concepts.get(rel.lstrip("/"))

    def links_from(self, rel: str) -> list[Link]:
        concept = self.concepts.get(rel)
        if concept is None:
            return []
        return extract_links(concept.body, rel, concept.body_start_line, self.exists)

    def edges_from(self, rel: str) -> list[str]:
        """Outbound graph edges: body links plus path fields that resolve to concepts."""
        concept = self.concepts.get(rel)
        if concept is None:
            return []
        targets = [lk.resolved for lk in self.links_from(rel) if lk.resolved and lk.resolved in self.concepts]
        targets += [t for t in path_field_edges(concept.meta, self.exists) if t in self.concepts]
        seen: dict[str, None] = {}
        for t in targets:
            if t != rel:
                seen.setdefault(t, None)
        return list(seen)

    def backlinks(self) -> dict[str, list[str]]:
        back: dict[str, list[str]] = {p: [] for p in self.concepts}
        for src in self.concepts:
            for dst in self.edges_from(src):
                back[dst].append(src)
        return back


def iter_bundle_files(root: Path) -> list[str]:
    """Bundle-relative POSIX paths of every file, excluding dot-paths and escaping symlinks."""
    root = root.resolve()
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fname in filenames:
            if fname.startswith("."):
                continue
            full = Path(dirpath) / fname
            if full.is_symlink():
                try:
                    full.resolve().relative_to(root)
                except ValueError:
                    continue  # symlink leaves the bundle
            out.append(full.relative_to(root).as_posix())
    return out
