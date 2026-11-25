"""Deterministic conflict resolution, following okf-consume's order.

When two concepts disagree, prefer: current status, then higher trust tier,
then not stale, then the later ``generated.at``. This lives in code so every
model gets the same answer and the reason can be shown to the user.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from okf.bundle import Bundle
from okf.model import Concept
from okf.trust import status_rank, trust_info

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Ranked:
    concept: Concept
    key: tuple[int, int, int, datetime]
    reason: str


def _key(concept: Concept, now: datetime | None) -> tuple[int, int, int, datetime]:
    info = trust_info(concept, now)
    return (
        status_rank(info.status),
        info.tier.rank,
        0 if info.stale else 1,
        info.generated_at or _EPOCH,
    )


def rank_conflicting(concepts: Sequence[Concept], now: datetime | None = None) -> list[Ranked]:
    """Order concepts best-first and explain each position."""
    keyed = [(c, _key(c, now)) for c in concepts]
    keyed.sort(key=lambda pair: pair[1], reverse=True)
    out: list[Ranked] = []
    for concept, key in keyed:
        info = trust_info(concept, now)
        out.append(Ranked(concept=concept, key=key, reason=info.label()))
    return out


def follow_superseded(bundle: Bundle, path: str, max_hops: int = 10) -> list[str]:
    """Follow ``superseded_by`` from a deprecated concept. Returns the chain, start first."""
    chain = [path]
    current = bundle.get(path)
    seen = {path}
    while current is not None and current.superseded_by and len(chain) <= max_hops:
        nxt = current.superseded_by.lstrip("/")
        if nxt in seen:
            break
        chain.append(nxt)
        seen.add(nxt)
        current = bundle.get(nxt)
    return chain
