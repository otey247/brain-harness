"""Producer-side helpers: frontmatter edits, index regeneration, log entries.

Rules from SPEC §4.1 and okf-generate:
- preserve unknown keys and don't re-serialize values you didn't change;
- regenerators keep the root index.md frontmatter;
- log.md has dated ``## YYYY-MM-DD`` headings, newest first;
- a producer never writes ``verified`` for its own work (enforced in
  :func:`stamp_generated`, which refuses to touch ``verified``).

Frontmatter edits use ruamel.yaml in round-trip mode so comments, key order and
quoting survive. It is imported lazily so readers don't need it.
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from okf.bundle import Bundle, split_frontmatter

FORBIDDEN_PRODUCER_KEYS = frozenset({"verified"})


def _ruamel() -> Any:
    try:
        from ruamel.yaml import YAML
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError("okf writer needs ruamel.yaml: install okf[write]") from exc
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def set_frontmatter(text: str, updates: dict[str, Any], *, allow_verified: bool = False) -> str:
    """Return ``text`` with top-level frontmatter keys set, everything else untouched.

    A value of ``None`` removes the key. The body is returned byte for byte.
    """
    if not allow_verified and FORBIDDEN_PRODUCER_KEYS & updates.keys():
        raise PermissionError("producers never write `verified` for their own work")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        head, body = "", text
    else:
        end = next(i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") in ("---", "..."))
        head, body = "".join(lines[1:end]), "".join(lines[end + 1 :])
    yaml = _ruamel()
    data = yaml.load(head) if head.strip() else None
    if data is None:
        from ruamel.yaml.comments import CommentedMap

        data = CommentedMap()
    for key, value in updates.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    buf = io.StringIO()
    yaml.dump(data, buf)
    return f"---\n{buf.getvalue()}---\n{body}"


def stamp_generated(text: str, producer: str, at: datetime | None = None) -> str:
    """Set ``generated: {by, at}``. ``producer`` should be ``<harness>/<version>+<model>``."""
    when = (at or datetime.now(UTC)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return set_frontmatter(text, {"generated": {"by": producer, "at": when}})


def render_index(bundle: Bundle, directory: str = "") -> str:
    """Render ``index.md`` for ``directory`` (``""`` = bundle root).

    Lists ``* [Title](url) - description`` grouped under a heading per type, plus
    links to child directories that hold concepts. The root keeps its frontmatter.
    """
    prefix = f"{directory.rstrip('/')}/" if directory else ""
    groups: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
    subdirs: set[str] = set()
    for rel, concept in sorted(bundle.concepts.items()):
        if not rel.startswith(prefix):
            continue
        rest = rel[len(prefix) :]
        if "/" in rest:
            subdirs.add(rest.split("/", 1)[0])
            continue
        groups[concept.type].append((concept.title, rest, concept.description))

    out: list[str] = []
    if not directory:
        meta_text = _root_frontmatter_block(bundle.root / "index.md")
        if meta_text:
            out.append(meta_text)
    title = bundle.root_index_meta.get("title") if not directory else directory.rsplit("/", 1)[-1]
    out.append(f"# {title or 'Index'}\n")
    for type_name in sorted(groups):
        out.append(f"\n## {type_name}\n\n")
        for item_title, href, desc in groups[type_name]:
            out.append(f"* [{item_title}]({href})" + (f" - {desc}" if desc else "") + "\n")
    if subdirs:
        out.append("\n## Sections\n\n")
        for sub in sorted(subdirs):
            out.append(f"* [{sub}]({sub}/index.md)\n")
    return "".join(out)


def _root_frontmatter_block(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    fm = split_frontmatter(text)
    if not fm.has_frontmatter:
        return ""
    end = len(text) - len(fm.body)
    return text[:end] + ("" if text[:end].endswith("\n\n") else "\n")


def write_indexes(bundle: Bundle) -> list[str]:
    """Regenerate every ``index.md`` (root and each directory holding concepts)."""
    dirs = {""}
    for rel in bundle.concepts:
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    written: list[str] = []
    for d in sorted(dirs):
        target = bundle.root / d / "index.md" if d else bundle.root / "index.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_index(bundle, d), encoding="utf-8")
        written.append(target.relative_to(bundle.root).as_posix())
    return written


def append_log(log_path: Path, entry: str, day: date | None = None) -> None:
    """Add a bullet under today's ``## YYYY-MM-DD`` heading, creating it at the top."""
    day = day or datetime.now(UTC).date()
    heading = f"## {day.isoformat()}"
    bullet = f"- {entry.strip()}\n"
    text = log_path.read_text(encoding="utf-8") if log_path.exists() else "# Log\n"
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip() == heading:
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            lines.insert(j, bullet)
            log_path.write_text("".join(lines), encoding="utf-8")
            return
    first = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    block = [f"{heading}\n", "\n", bullet, "\n"]
    if first == len(lines) and lines and not lines[-1].endswith("\n\n"):
        block.insert(0, "\n")
    lines[first:first] = block
    log_path.write_text("".join(lines), encoding="utf-8")
