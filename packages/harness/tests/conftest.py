from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from okf import Bundle

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "bundles" / "example"
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def bundle() -> Bundle:
    return Bundle.load(EXAMPLE)


@pytest.fixture
def settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    from brain_harness.config import Settings

    return Settings.model_validate(
        {
            "bundles": {"example": {"path": str(EXAMPLE)}},
            "default_bundle": "example",
            "scratch_dir": str(tmp_path / "scratch"),
            "run_log_dir": str(tmp_path / "runs"),
        }
    )
