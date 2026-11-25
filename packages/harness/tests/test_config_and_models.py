from __future__ import annotations

from pathlib import Path

import pytest
from brain_harness.config import BundleConfig, RoleModel, load_settings
from brain_harness.models.registry import ProviderNotAllowed, check_allowed

ROOT = Path(__file__).resolve().parents[3]


def test_repo_config_loads(monkeypatch):
    monkeypatch.delenv("BRAIN_BUNDLE", raising=False)
    monkeypatch.setenv("BRAIN_PLANNER_MODEL", "test:planner")
    monkeypatch.setenv("BRAIN_SEARCHER_MODEL", "test:searcher")
    settings = load_settings(ROOT / "config")
    assert settings.default_bundle == "example"
    assert settings.caps.grep_matches == 100
    assert settings.roles and settings.roles.planner.model == "test:planner"


def test_env_bundle_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAIN_BUNDLE", str(tmp_path))
    settings = load_settings(tmp_path / "missing-config")
    assert settings.bundle().path == tmp_path


def test_provider_allowlist():
    bundle = BundleConfig(path=Path("."), allowed_providers=["azure"])
    check_allowed(RoleModel(model="azure:dep"), bundle)
    with pytest.raises(ProviderNotAllowed):
        check_allowed(RoleModel(model="azure:dep", fallbacks=["openai:x"]), bundle)
