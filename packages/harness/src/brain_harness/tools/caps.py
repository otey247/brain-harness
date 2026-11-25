"""Output caps for tool results.

Every harness studied caps tool output (Codex ~10k tokens, Claude Code and
OpenHands 30-50k chars). Over the cap we keep head and tail, mark the cut with
the original size, and spill the full text to a scratch file the agent can grep.
Results stay inline: the grep paper found file-only delivery hurt some
harness/model pairs badly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

CHARS_PER_TOKEN = 4  # conservative estimate; exact counts come from the provider's usage


def estimate_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


@dataclass(frozen=True)
class Capped:
    text: str
    truncated: bool
    original_tokens: int
    spill_path: str | None = None


def cap_output(text: str, max_tokens: int, spill_dir: Path | None = None, label: str = "output") -> Capped:
    original = estimate_tokens(text)
    if original <= max_tokens:
        return Capped(text=text, truncated=False, original_tokens=original)

    spill_path: str | None = None
    if spill_dir is not None:
        spill_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        path = spill_dir / f"{label}-{digest}.txt"
        path.write_text(text, encoding="utf-8")
        spill_path = f"scratch:{path.name}"

    budget_chars = max_tokens * CHARS_PER_TOKEN
    head = text[: budget_chars // 2]
    tail = text[-(budget_chars // 2) :]
    head = head[: head.rfind("\n") + 1] or head
    tail = tail[tail.find("\n") + 1 :] or tail
    lines = text.count("\n") + 1
    marker = (
        f"\n[... truncated: original ~{original} tokens, {lines} lines"
        + (f"; full output saved as {spill_path}; read or grep it with path='{spill_path}'" if spill_path else "")
        + "; narrow the query or page with offset ...]\n"
    )
    return Capped(text=head + marker + tail, truncated=True, original_tokens=original, spill_path=spill_path)
