"""Trust tier, lifecycle status and freshness (SPEC §5).

These are computed in code and attached to every search hit so the model never
has to work them out from raw frontmatter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from okf.model import Concept, Event, Status, TrustTier, is_empty


def current_verifications(concept: Concept) -> list[Event]:
    """Verifications that count: ``at >= generated.at`` (v0.3 breaking change).

    With no parseable ``generated.at`` every verification with a parseable
    ``at`` counts. A verification whose ``at`` won't parse never counts.
    """
    generated = concept.generated
    floor = generated.at if generated else None
    return [v for v in concept.verified if v.at is not None and (floor is None or v.at >= floor)]


def trust_tier(concept: Concept) -> TrustTier:
    current = current_verifications(concept)
    if not current:
        return TrustTier.UNVERIFIED
    if any(v.is_human for v in current):
        return TrustTier.HUMAN_REVIEWED
    return TrustTier.MACHINE_CONFIRMED


def is_stale(concept: Concept, now: datetime | None = None) -> bool:
    """Stale means "check again", not "false".

    A ``stale_after`` that won't parse is never treated as fresh.
    """
    raw = concept.stale_after_raw
    if is_empty(raw):
        return False
    instant = concept.stale_after
    if instant is None:
        return True
    return (now or datetime.now(UTC)) >= instant


def status_rank(status: Status) -> int:
    """Higher is more current. Unknown status counts as not current (SPEC §5)."""
    return {Status.STABLE: 2, Status.DRAFT: 1, Status.DEPRECATED: 0, Status.UNKNOWN: 0}[status]


def is_current(concept: Concept) -> bool:
    return status_rank(concept.status) > 0


@dataclass(frozen=True)
class TrustInfo:
    tier: TrustTier
    status: Status
    stale: bool
    superseded_by: str | None
    generated_by: str | None
    generated_at: datetime | None

    def label(self) -> str:
        parts = [self.tier.value, self.status.value]
        if self.stale:
            parts.append("stale")
        if self.superseded_by:
            parts.append(f"superseded by {self.superseded_by}")
        return ", ".join(parts)

    def as_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier.value,
            "status": self.status.value,
            "stale": self.stale,
            "superseded_by": self.superseded_by,
            "generated_by": self.generated_by,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }


def trust_info(concept: Concept, now: datetime | None = None) -> TrustInfo:
    generated = concept.generated
    return TrustInfo(
        tier=trust_tier(concept),
        status=concept.status,
        stale=is_stale(concept, now),
        superseded_by=concept.superseded_by if concept.status is Status.DEPRECATED else None,
        generated_by=generated.by if generated else None,
        generated_at=generated.at if generated else None,
    )
