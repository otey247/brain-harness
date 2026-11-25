"""Bundle validation.

Errors (E) break conformance (SPEC §11). Warnings (W) are quality checks a
consumer must tolerate but a producer should fix. Codes are this project's own;
they are not guaranteed to match the upstream ``scripts/validate.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from okf.bundle import Bundle, split_frontmatter
from okf.model import Status, as_list, is_empty, parse_instant
from okf.yaml12 import Yaml12Error

_LOG_HEADING = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\b")
_FOOTNOTE_REF = re.compile(r"\[\^([^\]]+)\](?!:)")


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.message}"


def validate(bundle: Bundle) -> list[Issue]:
    issues: list[Issue] = [Issue(p.code, Severity.ERROR, p.path, p.line, p.message) for p in bundle.issues]
    issues += _check_reserved(bundle)
    for path, concept in bundle.concepts.items():
        meta = concept.meta
        status = meta.get("status")
        if not is_empty(status) and str(status) not in {s.value for s in Status if s is not Status.UNKNOWN}:
            issues.append(Issue("W160", Severity.WARNING, path, 1, f"unknown status {status!r}"))
        if concept.status is Status.DEPRECATED and not concept.superseded_by:
            issues.append(Issue("W130", Severity.WARNING, path, 1, "deprecated without superseded_by"))
        if concept.superseded_by and concept.status is not Status.DEPRECATED:
            issues.append(Issue("W131", Severity.WARNING, path, 1, "superseded_by is only meaningful when deprecated"))
        if concept.superseded_by and not bundle.get(concept.superseded_by):
            issues.append(
                Issue("W121", Severity.WARNING, path, 1, f"superseded_by target missing: {concept.superseded_by}")
            )
        if not is_empty(meta.get("stale_after")) and parse_instant(meta.get("stale_after")) is None:
            issues.append(
                Issue("W140", Severity.WARNING, path, 1, "stale_after is not an RFC 3339 instant; treated as stale")
            )
        for item in as_list(meta.get("verified")):
            if not isinstance(item, dict) or is_empty(item.get("by")) or is_empty(item.get("at")):
                issues.append(Issue("W141", Severity.WARNING, path, 1, "verified entries need both by and at"))
        generated = meta.get("generated")
        if generated is not None and (not isinstance(generated, dict) or is_empty(generated.get("by"))):
            issues.append(Issue("W142", Severity.WARNING, path, 1, "generated needs a by"))
        source_ids = set()
        for item in as_list(meta.get("sources")):
            if not isinstance(item, dict) or is_empty(item.get("resource")):
                issues.append(Issue("W151", Severity.WARNING, path, 1, "sources entries need a resource"))
            elif not is_empty(item.get("id")):
                source_ids.add(str(item["id"]))
        defined = set(re.findall(r"^\[\^([^\]]+)\]:", concept.body, flags=re.MULTILINE))
        for offset, line in enumerate(concept.body.splitlines()):
            for label in _FOOTNOTE_REF.findall(line):
                if label not in defined and label not in source_ids:
                    issues.append(
                        Issue(
                            "W150",
                            Severity.WARNING,
                            path,
                            concept.body_start_line + offset,
                            f"footnote [^{label}] matches no definition or sources id",
                        )
                    )
        for link in bundle.links_from(path):
            if not link.is_url and (link.resolved is None or not bundle.exists(link.resolved)):
                issues.append(Issue("W120", Severity.WARNING, path, link.line, f"broken link: {link.target}"))
    return sorted(issues, key=lambda i: (i.path, i.line, i.code))


def _check_reserved(bundle: Bundle) -> list[Issue]:
    issues: list[Issue] = []
    for rel in bundle.reserved:
        text = (bundle.root / rel).read_text(encoding="utf-8", errors="replace")
        name = rel.rsplit("/", 1)[-1]
        try:
            fm = split_frontmatter(text)
        except Yaml12Error as exc:
            issues.append(Issue("E101", Severity.ERROR, rel, 1, f"invalid frontmatter: {exc}"))
            continue
        if name == "index.md" and rel != "index.md" and fm.has_frontmatter:
            issues.append(Issue("E110", Severity.ERROR, rel, 1, "only the bundle-root index.md may have frontmatter"))
        if name == "log.md":
            if fm.has_frontmatter:
                issues.append(Issue("E111", Severity.ERROR, rel, 1, "log.md must not have frontmatter"))
            dates = [m.group(1) for m in map(_LOG_HEADING.match, text.splitlines()) if m]
            if dates != sorted(dates, reverse=True):
                issues.append(Issue("W112", Severity.WARNING, rel, 1, "log.md entries should be newest first"))
    if "index.md" in bundle.reserved and is_empty(bundle.root_index_meta.get("description")):
        issues.append(
            Issue("W113", Severity.WARNING, "index.md", 1, "root index.md should describe the bundle (description)")
        )
    return issues


def is_conformant(issues: list[Issue]) -> bool:
    return not any(i.severity is Severity.ERROR for i in issues)
