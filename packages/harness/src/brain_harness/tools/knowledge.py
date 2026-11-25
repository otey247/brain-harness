"""Read-side tools over one OKF bundle.

Design rules (see the design doc, Architecture > Tools):
- paths resolve inside the bundle root only; no symlinks out, no shell;
- every result is capped, with head and tail kept and the rest spilled;
- every hit carries its trust label (tier, status, staleness, superseded_by),
  computed in code so the model never derives it from raw frontmatter;
- line numbers are file line numbers, so citations point at the real file.

Each method returns plain text, which is what the model reads. The same
instance backs the agent loop and the MCP server.
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from okf import Bundle, Status, TrustTier, trust_info
from okf.model import Concept, parse_instant

from brain_harness.config import Caps
from brain_harness.index.sqlite_index import SqliteIndex
from brain_harness.tools.caps import cap_output


class ToolError(ValueError):
    """A recoverable error the model should read and fix (bad path, bad regex)."""


@dataclass
class EvidenceLedger:
    """What the agent actually opened during a run: used for evals and citation checks."""

    reads: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    grep_hits: set[str] = field(default_factory=set)
    calls: Counter[str] = field(default_factory=Counter)

    def record_read(self, path: str, start: int, end: int) -> None:
        self.reads.setdefault(path, []).append((start, end))

    def opened(self) -> set[str]:
        return set(self.reads)


class KnowledgeTools:
    def __init__(
        self,
        bundle: Bundle,
        caps: Caps | None = None,
        scratch_dir: Path | None = None,
        now: datetime | None = None,
        index: SqliteIndex | None = None,
    ) -> None:
        self.bundle = bundle
        self.index = index
        self.root = bundle.root
        self.caps = caps or Caps()
        self.scratch_dir = scratch_dir
        self._now = now
        self.ledger = EvidenceLedger()
        self._rg = shutil.which("rg")

    # ---- helpers ---------------------------------------------------------------
    @property
    def now(self) -> datetime:
        return self._now or datetime.now(UTC)

    def _cap(self, text: str, label: str) -> str:
        return cap_output(text, self.caps.tool_output_tokens, self.scratch_dir, label).text

    def _label(self, rel: str) -> str:
        concept = self.bundle.concepts.get(rel)
        if concept is None:
            return "not a concept"
        return f"{concept.type} · {trust_info(concept, self.now).label()}"

    def _safe_path(self, path: str) -> tuple[Path, str]:
        """Resolve ``path`` inside the bundle (or the scratch dir for ``scratch:`` paths)."""
        if path.startswith("scratch:"):
            if self.scratch_dir is None:
                raise ToolError("no scratch directory is configured")
            base = self.scratch_dir.resolve()
            target = (base / path.removeprefix("scratch:")).resolve()
            if not target.is_relative_to(base) or not target.is_file():
                raise ToolError(f"no such scratch file: {path}")
            return target, path
        rel = path.strip().lstrip("/")
        target = (self.root / rel).resolve()
        if not target.is_relative_to(self.root):
            raise ToolError(f"path is outside the bundle: {path}")
        if any(part.startswith(".") for part in Path(rel).parts):
            raise ToolError(f"dot-paths are excluded from the bundle: {path}")
        return target, target.relative_to(self.root).as_posix() if target != self.root else ""

    # ---- list -------------------------------------------------------------------
    def list(self, directory: str = "") -> str:
        """Walk the bundle one level: the directory's index.md, then its concepts and subdirectories."""
        target, rel = self._safe_path(directory)
        if not target.is_dir():
            raise ToolError(f"not a directory: {directory or '/'}")
        prefix = f"{rel}/" if rel else ""
        lines: list[str] = []
        if not rel and self.bundle.description:
            lines.append(f"Bundle: {self.bundle.root_index_meta.get('title', '')} - {self.bundle.description}")
        index = target / "index.md"
        if index.exists():
            lines.append(f"index.md exists at {prefix}index.md (read it for the curated map)")
        subdirs: set[str] = set()
        entries: list[str] = []
        for path, concept in sorted(self.bundle.concepts.items()):
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix) :]
            if "/" in rest:
                subdirs.add(rest.split("/", 1)[0])
                continue
            desc = f" - {concept.description}" if concept.description else ""
            entries.append(f"{path}  [{self._label(path)}]  {concept.title}{desc}")
        lines += [f"{prefix}{d}/" for d in sorted(subdirs)]
        lines += entries[: self.caps.list_entries]
        if len(entries) > self.caps.list_entries:
            lines.append(f"[... {len(entries) - self.caps.list_entries} more; use frontmatter_query to filter]")
        return self._cap("\n".join(lines) or "(empty)", "list")

    # ---- glob -------------------------------------------------------------------
    def glob(self, pattern: str) -> str:
        """Paths matching a glob pattern (e.g. ``decisions/*.md``), newest first."""
        files = [p for p in self.bundle.concepts if fnmatch.fnmatch(p, pattern)]
        files += [p for p in self.bundle.assets if fnmatch.fnmatch(p, pattern)]
        files.sort(key=lambda p: (self.root / p).stat().st_mtime, reverse=True)
        shown = files[: self.caps.glob_paths]
        lines = [f"{p}  [{self._label(p)}]" for p in shown]
        if len(files) > len(shown):
            lines.append(f"[... {len(files) - len(shown)} more paths; narrow the pattern]")
        return "\n".join(lines) or "(no matches)"

    # ---- grep -------------------------------------------------------------------
    def grep(
        self,
        pattern: str,
        path: str = "",
        mode: str = "content",
        ignore_case: bool = True,
        context: int = 0,
        glob: str = "*.md",
        head_limit: int | None = None,
        offset: int = 0,
    ) -> str:
        """Regex search. ``mode`` is ``files`` (paths only), ``content`` (matching lines) or ``count``."""
        if mode not in {"files", "content", "count"}:
            raise ToolError("mode must be files, content or count")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"invalid regex: {exc}") from exc
        target, _ = self._safe_path(path)
        limit = min(head_limit or self.caps.grep_matches, self.caps.grep_matches)
        rows = self._grep_rows(pattern, target, mode, ignore_case, max(0, min(context, 5)), glob)
        rows = rows[offset : offset + limit + 1]
        more = len(rows) > limit
        rows = rows[:limit]

        out: list[str] = []
        current_file: str | None = None
        for file_rel, payload in rows:
            if not file_rel.startswith("scratch:") and file_rel in self.bundle.concepts:
                self.ledger.grep_hits.add(file_rel)
            label = "" if file_rel.startswith("scratch:") else f"  [{self._label(file_rel)}]"
            if mode == "files":
                out.append(f"{file_rel}{label}")
            elif mode == "count":
                out.append(f"{file_rel}: {payload}{label}")
            else:
                if file_rel != current_file:
                    out.append(f"== {file_rel}{label}")
                    current_file = file_rel
                out.append(payload)
        if more:
            out.append(f"[... more results; call again with offset={offset + limit}]")
        return self._cap("\n".join(out) or "(no matches)", "grep")

    def _grep_rows(
        self, pattern: str, target: Path, mode: str, ignore_case: bool, context: int, glob: str
    ) -> list[tuple[str, str]]:
        scratch = self.scratch_dir.resolve() if self.scratch_dir else None
        base = scratch if scratch and target.is_relative_to(scratch) else self.root

        def rel_of(p: str) -> str:
            path = Path(p)
            full = path if path.is_absolute() else (Path.cwd() / path)
            r = full.resolve().relative_to(base).as_posix()
            return f"scratch:{r}" if base == scratch else r

        if self._rg:
            args = [
                self._rg,
                "--color",
                "never",
                "--no-heading",
                "--no-follow",
                "--with-filename",
                "--null",
                "-e",
                pattern,
            ]
            if ignore_case:
                args.append("-i")
            if glob and base != scratch:
                args += ["-g", glob]
            if mode == "files":
                args.append("-l")
            elif mode == "count":
                args.append("-c")
            else:
                args += ["-n"] + (["-C", str(context)] if context else [])
            args.append(str(target))
            proc = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
            if proc.returncode not in (0, 1):
                raise ToolError(proc.stderr.strip() or "grep failed")
            rows: list[tuple[str, str]] = []
            if mode == "files":
                return sorted((rel_of(p), "") for p in proc.stdout.split("\0") if p.strip())
            for line in proc.stdout.splitlines():
                if line == "--" or "\0" not in line:
                    continue
                name, _, rest = line.partition("\0")
                if mode == "count":
                    rows.append((rel_of(name), rest))
                    continue
                m = re.match(r"^(\d+)([:-])(.*)$", rest)
                if m:  # ":" marks a matching line, "-" a context line
                    rows.append((rel_of(name), f"{m.group(1)}{m.group(2)} {m.group(3)}"))
            return sorted(rows, key=lambda r: r[0]) if mode != "content" else rows
        return self._grep_python(pattern, target, base, mode, ignore_case, glob, rel_of)

    def _grep_python(self, pattern, target, base, mode, ignore_case, glob, rel_of):  # type: ignore[no-untyped-def]
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
        rows: list[tuple[str, str]] = []
        for f in files:
            if any(part.startswith(".") for part in f.relative_to(base).parts):
                continue
            if glob and target.is_dir() and not fnmatch.fnmatch(f.name, glob):
                continue
            hits = [
                (i, line) for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1) if regex.search(line)
            ]
            if not hits:
                continue
            rel = rel_of(str(f))
            if mode == "files":
                rows.append((rel, ""))
            elif mode == "count":
                rows.append((rel, str(len(hits))))
            else:
                rows += [(rel, f"{i}: {line}") for i, line in hits]
        return rows

    # ---- read -------------------------------------------------------------------
    def read(self, path: str, offset: int = 1, limit: int | None = None, frontmatter_only: bool = False) -> str:
        """Read a file with file line numbers. ``offset`` is the 1-based first line."""
        target, rel = self._safe_path(path)
        if not target.is_file():
            hint = self._suggest(rel)
            raise ToolError(f"no such file: {path}" + (f". Did you mean {hint}?" if hint else ""))
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        concept = self.bundle.concepts.get(rel)
        if frontmatter_only:
            end = (concept.body_start_line - 1) if concept else min(len(lines), 40)
            start, stop = 1, max(end, 1)
        else:
            start = max(1, offset)
            stop = min(len(lines), start - 1 + min(limit or self.caps.read_lines, self.caps.read_lines))
        width = len(str(stop))
        numbered = [
            f"{i:>{width}}\t{line[: self.caps.read_line_chars]}"
            + (" [line cut]" if len(line) > self.caps.read_line_chars else "")
            for i, line in enumerate(lines[start - 1 : stop], start)
        ]
        header = f"# {rel}" + (f"  [{self._label(rel)}]" if concept else "")
        if concept and concept.status is Status.DEPRECATED and concept.superseded_by:
            header += f"\n# deprecated: prefer {concept.superseded_by.lstrip('/')}"
        footer = (
            f"\n[lines {start}-{stop} of {len(lines)}" + ("; call again with offset" if stop < len(lines) else "") + "]"
        )
        if not rel.startswith("scratch:"):
            self.ledger.record_read(rel, start, stop)
        return self._cap(header + "\n" + "\n".join(numbered) + footer, "read")

    def _suggest(self, rel: str) -> str | None:
        stem = Path(rel).stem.lower()
        for path in self.bundle.concepts:
            if stem and stem in path.lower():
                return path
        return None

    # ---- frontmatter_query -----------------------------------------------------
    def frontmatter_query(
        self,
        type: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        tier: str | None = None,
        stale: bool | None = None,
        updated_since: str | None = None,
        text: str | None = None,
    ) -> str:
        """Filter concepts by parsed frontmatter. ``updated_since`` compares ``generated.at`` (RFC 3339 or date)."""
        since = (
            parse_instant(updated_since if updated_since and "T" in updated_since else f"{updated_since}T00:00:00Z")
            if updated_since
            else None
        )
        if updated_since and since is None:
            raise ToolError("updated_since must be a date (YYYY-MM-DD) or RFC 3339 instant")
        if tier and tier not in {t.value for t in TrustTier}:
            raise ToolError(f"tier must be one of {[t.value for t in TrustTier]}")
        rows: list[str] = []
        needle = text.lower() if text else None
        for path, concept in sorted(self.bundle.concepts.items()):
            info = trust_info(concept, self.now)
            if type and concept.type != type:
                continue
            if tag and tag not in concept.tags:
                continue
            if status and info.status.value != status:
                continue
            if tier and info.tier.value != tier:
                continue
            if stale is not None and info.stale != stale:
                continue
            if since and (info.generated_at is None or info.generated_at < since):
                continue
            if needle and needle not in f"{concept.title} {concept.description or ''}".lower():
                continue
            rows.append(self._row(path, concept))
        shown = rows[: self.caps.list_entries]
        if len(rows) > len(shown):
            shown.append(f"[... {len(rows) - len(shown)} more; add filters]")
        return "\n".join(shown) or "(no concepts match)"

    def _row(self, path: str, concept: Concept) -> str:
        info = trust_info(concept, self.now)
        when = info.generated_at.date().isoformat() if info.generated_at else "?"
        tags = ",".join(concept.tags)
        return f"{path}  [{concept.type} · {info.label()} · generated {when}]  {concept.title}" + (
            f"  tags={tags}" if tags else ""
        )

    # ---- links ------------------------------------------------------------------
    def links(self, path: str, direction: str = "both", depth: int = 1) -> str:
        """Outbound links, backlinks, or both, up to depth 2."""
        _, rel = self._safe_path(path)
        if rel not in self.bundle.concepts:
            raise ToolError(f"not a concept: {path}")
        if direction not in {"out", "in", "both"}:
            raise ToolError("direction must be out, in or both")
        depth = max(1, min(depth, 2))
        back = self.bundle.backlinks() if direction in {"in", "both"} else {}
        out: list[str] = []
        frontier = {rel}
        seen = {rel}
        for level in range(1, depth + 1):
            nxt: set[str] = set()
            for node in sorted(frontier):
                if direction in {"out", "both"}:
                    for dst in self.bundle.edges_from(node):
                        out.append(f"{'  ' * (level - 1)}{node} -> {dst}  [{self._label(dst)}]")
                        nxt.add(dst)
                if direction in {"in", "both"}:
                    for src in back.get(node, []):
                        out.append(f"{'  ' * (level - 1)}{node} <- {src}  [{self._label(src)}]")
                        nxt.add(src)
            frontier = nxt - seen
            seen |= nxt
        urls = [lk.target for lk in self.bundle.links_from(rel) if lk.is_url]
        out += [f"{rel} -> {u}  [external]" for u in urls]
        return "\n".join(out[: self.caps.link_edges]) or "(no links)"

    # ---- search (optional index) -------------------------------------------------
    def search(self, query: str, k: int | None = None) -> str:
        """Ranked pages from the local index (BM25, or hybrid when vectors are configured).

        Off unless an index is attached; enable it only where evals show a gain.
        """
        if self.index is None:
            raise ToolError("search is not enabled for this bundle; use grep, glob and frontmatter_query")
        hits = self.index.search(query, min(k or self.caps.search_pages, self.caps.search_pages))
        lines = [f"{h.path}  [{self._label(h.path)}]  {' '.join(h.snippet.split())}" for h in hits]
        commit = self.index.indexed_commit
        if commit:
            lines.append(f"[index built at commit {commit[:12]}]")
        return self._cap("\n".join(lines) or "(no matches)", "search")
