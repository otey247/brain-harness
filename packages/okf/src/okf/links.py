"""Link extraction and resolution (SPEC §6).

Only standard Markdown ``[text](target)`` links count; ``[[wikilinks]]`` are
explicitly not links. A target with a scheme is an absolute URL, a leading
``/`` resolves from the bundle root, anything else resolves relative to the
file. v0.2 bundles resolved everything from the root, so a relative target that
doesn't exist falls back to root resolution. Broken links are accepted.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass

_FENCE = re.compile(r"^(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")
# [text](target "optional title") — not preceded by "!" handled separately for images.
_LINK = re.compile(r"(?<!\!)\[(?P<text>[^\]]*)\]\((?P<target><[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


@dataclass(frozen=True)
class Link:
    text: str
    target: str  # as written
    line: int  # 1-based line in the file
    resolved: str | None  # bundle-relative path, or None for URLs and targets outside the bundle
    is_url: bool
    fragment: str | None = None


def iter_raw_links(body: str, first_line: int = 1) -> list[tuple[str, str, int]]:
    """Return ``(text, target, line)`` for every Markdown link outside code."""
    out: list[tuple[str, str, int]] = []
    in_fence = False
    for offset, line in enumerate(body.splitlines()):
        if _FENCE.match(line.lstrip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        scrubbed = _INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line)
        for match in _LINK.finditer(scrubbed):
            target = match.group("target").strip("<>")
            out.append((match.group("text"), target, first_line + offset))
    return out


def resolve_target(
    target: str,
    from_path: str,
    exists: Callable[[str], bool] | None = None,
) -> tuple[str | None, bool, str | None]:
    """Resolve ``target`` written in ``from_path``.

    Returns ``(bundle_relative_path_or_None, is_url, fragment)``.
    """
    if _SCHEME.match(target):
        return None, True, None
    path, _, fragment = target.partition("#")
    if not path:  # same-file anchor
        return from_path, False, fragment or None
    if path.startswith("/"):
        candidate = posixpath.normpath(path.lstrip("/"))
    else:
        base = posixpath.dirname(from_path)
        candidate = posixpath.normpath(posixpath.join(base, path))
        if exists is not None and not exists(candidate):
            root_candidate = posixpath.normpath(path)
            if not root_candidate.startswith("..") and exists(root_candidate):
                candidate = root_candidate  # v0.2 fallback
    if candidate.startswith("..") or candidate == ".":
        return None, False, fragment or None
    return candidate, False, fragment or None


def extract_links(
    body: str,
    from_path: str,
    first_line: int = 1,
    exists: Callable[[str], bool] | None = None,
) -> list[Link]:
    links: list[Link] = []
    for text, target, line in iter_raw_links(body, first_line):
        resolved, is_url, fragment = resolve_target(target, from_path, exists)
        links.append(Link(text=text, target=target, line=line, resolved=resolved, is_url=is_url, fragment=fragment))
    return links


PATH_FIELDS = ("superseded_by",)


def path_field_edges(meta: dict[str, object], exists: Callable[[str], bool] | None = None) -> list[str]:
    """Frontmatter path fields that resolve to a concept are graph edges too."""
    out: list[str] = []
    for key in PATH_FIELDS:
        value = meta.get(key)
        if isinstance(value, str) and value:
            resolved, is_url, _ = resolve_target(value if value.startswith("/") else "/" + value, "", exists)
            if resolved and not is_url:
                out.append(resolved)
    return out
