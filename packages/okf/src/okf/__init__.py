"""Open Knowledge Format (OKF) v0.3 reader, validator and writer.

No model or network dependencies: this package is safe to publish on its own.
"""

from okf.bundle import Bundle, parse_concept, split_frontmatter
from okf.conflicts import follow_superseded, rank_conflicting
from okf.links import Link, extract_links
from okf.model import Concept, Status, TrustTier
from okf.trust import TrustInfo, is_stale, trust_info, trust_tier
from okf.validate import Issue, Severity, is_conformant, validate

__all__ = [
    "Bundle",
    "Concept",
    "Issue",
    "Link",
    "Severity",
    "Status",
    "TrustInfo",
    "TrustTier",
    "extract_links",
    "follow_superseded",
    "is_conformant",
    "is_stale",
    "parse_concept",
    "rank_conflicting",
    "split_frontmatter",
    "trust_info",
    "trust_tier",
    "validate",
]

__version__ = "0.1.0"
SPEC_VERSION = "0.3"
