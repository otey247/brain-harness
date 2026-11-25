"""Citation post-check.

Every cited span must exist where the model says it does. A failed citation is
dropped and turned into a gap; it is never shown as support. Concepts used are
re-labelled from code so the tier and status shown to the user are never the
model's guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from okf import Bundle, trust_info

from brain_harness.agent.output import Answer, Citation, ConceptUsed

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


@dataclass
class CitationReport:
    valid: list[Citation] = field(default_factory=list)
    invalid: list[tuple[Citation, str]] = field(default_factory=list)

    @property
    def validity(self) -> float:
        total = len(self.valid) + len(self.invalid)
        return 1.0 if total == 0 else len(self.valid) / total


def check_citation(bundle: Bundle, citation: Citation, slack: int = 2) -> str | None:
    """Return None when valid, else the reason it failed.

    ``slack`` lines either side absorb off-by-one line numbers from the model.
    """
    path = citation.path.lstrip("/")
    concept = bundle.get(path)
    if concept is None:
        return "not a concept in this bundle"
    lines = concept.raw.splitlines()
    if citation.start_line > len(lines) or citation.end_line < citation.start_line:
        return "line range outside the file"
    lo = max(1, citation.start_line - slack)
    hi = min(len(lines), citation.end_line + slack)
    window = _norm(" ".join(lines[lo - 1 : hi]))
    quote = _norm(citation.quote.strip(" \"'…."))
    if not quote:
        return "empty quote"
    if quote not in window:
        return "quote not found at those lines"
    return None


def verify_answer(bundle: Bundle, answer: Answer, now: datetime | None = None) -> tuple[Answer, CitationReport]:
    report = CitationReport()
    for citation in answer.citations:
        reason = check_citation(bundle, citation)
        if reason is None:
            report.valid.append(citation)
        else:
            report.invalid.append((citation, reason))
    gaps = list(answer.gaps)
    gaps += [f"Unsupported citation removed ({c.path}#L{c.start_line}: {why})" for c, why in report.invalid]

    used: dict[str, ConceptUsed] = {}
    for citation in report.valid:
        path = citation.path.lstrip("/")
        concept = bundle.get(path)
        if concept is not None and path not in used:
            info = trust_info(concept, now)
            used[path] = ConceptUsed(path=path, tier=info.tier.value, status=info.status.value, stale=info.stale)

    checked = answer.model_copy(update={"citations": report.valid, "concepts_used": list(used.values()), "gaps": gaps})
    return checked, report
