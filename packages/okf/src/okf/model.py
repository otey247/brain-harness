"""Typed views over OKF concepts.

The raw frontmatter mapping is always kept (``Concept.meta``) so unknown keys,
including ``x-`` extensions, survive untouched. Typed accessors apply the
consumer rules from SPEC §11: null, empty and absent are the same; a single
item is accepted where a list is expected; a scalar ``tags`` is never split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    DRAFT = "draft"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    UNKNOWN = "unknown"


class TrustTier(StrEnum):
    UNVERIFIED = "unverified"
    MACHINE_CONFIRMED = "machine-confirmed"
    HUMAN_REVIEWED = "human-reviewed"

    @property
    def rank(self) -> int:
        return {"unverified": 0, "machine-confirmed": 1, "human-reviewed": 2}[self.value]


def is_empty(value: Any) -> bool:
    """SPEC §11: null, empty and absent are equivalent."""
    return value is None or value == "" or value == [] or value == {}


def as_list(value: Any) -> list[Any]:
    """SPEC §11: accept a single item where a list is expected."""
    if is_empty(value):
        return []
    if isinstance(value, list):
        return [v for v in value if not is_empty(v)]
    return [value]


def parse_instant(value: Any) -> datetime | None:
    """Parse an RFC 3339 instant. Returns None for anything that won't parse.

    A naive value (no offset) is rejected: OKF instants are absolute.
    """
    if is_empty(value):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class Source:
    resource: str
    id: str | None = None
    title: str | None = None
    author: str | None = None
    last_modified: datetime | None = None


@dataclass(frozen=True)
class Event:
    """A ``generated`` or ``verified`` event: an actor and an instant."""

    by: str
    at: datetime | None

    @property
    def is_human(self) -> bool:
        return self.by.startswith("human:")


@dataclass
class Concept:
    """One OKF concept: a ``.md`` file whose frontmatter has a ``type``."""

    path: str  # bundle-relative POSIX path, e.g. "projects/okf-harness.md"
    meta: dict[str, Any]
    body: str
    body_start_line: int = 1  # 1-based line number where the body begins in the file
    raw: str = field(default="", repr=False)

    @property
    def type(self) -> str:
        return str(self.meta.get("type", ""))

    @property
    def title(self) -> str:
        title = self.meta.get("title")
        if not is_empty(title):
            return str(title)
        stem = self.path.rsplit("/", 1)[-1].removesuffix(".md")
        return stem.replace("-", " ").replace("_", " ")

    @property
    def description(self) -> str | None:
        value = self.meta.get("description")
        return None if is_empty(value) else str(value)

    @property
    def tags(self) -> list[str]:
        return [str(t) for t in as_list(self.meta.get("tags"))]

    @property
    def status(self) -> Status:
        value = self.meta.get("status")
        if is_empty(value):
            return Status.STABLE
        try:
            return Status(str(value))
        except ValueError:
            return Status.UNKNOWN

    @property
    def superseded_by(self) -> str | None:
        value = self.meta.get("superseded_by")
        return None if is_empty(value) else str(value)

    @property
    def stale_after_raw(self) -> Any:
        return self.meta.get("stale_after")

    @property
    def stale_after(self) -> datetime | None:
        return parse_instant(self.meta.get("stale_after"))

    @property
    def sources(self) -> list[Source]:
        out: list[Source] = []
        for item in as_list(self.meta.get("sources")):
            if not isinstance(item, dict) or is_empty(item.get("resource")):
                continue
            out.append(
                Source(
                    resource=str(item["resource"]),
                    id=None if is_empty(item.get("id")) else str(item["id"]),
                    title=None if is_empty(item.get("title")) else str(item["title"]),
                    author=None if is_empty(item.get("author")) else str(item["author"]),
                    last_modified=parse_instant(item.get("last_modified")),
                )
            )
        return out

    @property
    def generated(self) -> Event | None:
        value = self.meta.get("generated")
        if not isinstance(value, dict) or is_empty(value.get("by")):
            return None
        return Event(by=str(value["by"]), at=parse_instant(value.get("at")))

    @property
    def verified(self) -> list[Event]:
        events: list[Event] = []
        for item in as_list(self.meta.get("verified")):
            if not isinstance(item, dict) or is_empty(item.get("by")) or is_empty(item.get("at")):
                continue
            events.append(Event(by=str(item["by"]), at=parse_instant(item.get("at"))))
        return events
