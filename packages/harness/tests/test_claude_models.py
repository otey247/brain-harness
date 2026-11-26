"""Claude as a first-class model: aliases, prompt caching, keys and env overrides. No network."""

from __future__ import annotations

from pathlib import Path

import pytest
from brain_harness.config import BundleConfig, RoleModel, Roles, load_settings
from brain_harness.models.registry import (
    ProviderNotAllowed,
    check_allowed,
    is_claude,
    missing_key,
    model_settings,
    normalize,
    provider_of,
    resolve,
)

CACHE_KEYS = {"anthropic_cache_instructions", "anthropic_cache_tool_definitions", "anthropic_cache"}


def test_claude_alias_normalizes_to_anthropic():
    assert normalize("claude:some-model") == "anthropic:some-model"
    assert normalize("openai:x") == "openai:x"
    assert normalize("test") == "test"
    assert provider_of("claude:some-model") == "anthropic"
    assert is_claude("claude:m") and is_claude("anthropic:m")
    assert not is_claude("openai:m") and not is_claude("bedrock:m")


def test_resolve_returns_anthropic_string_for_claude_alias(settings):
    settings.roles = Roles.model_validate({"planner": {"model": "claude:my-model"}})
    assert resolve(settings, "planner", settings.bundle()) == "anthropic:my-model"
    # Unset roles fall back to the planner's model.
    assert resolve(settings, "searcher", settings.bundle()) == "anthropic:my-model"


def test_prompt_cache_on_by_default_for_claude(settings):
    settings.roles = Roles.model_validate({"planner": {"model": "claude:m"}, "searcher": {"model": "openai:m"}})
    planner = model_settings(settings, "planner")
    assert CACHE_KEYS <= planner.keys() and planner["anthropic_cache"] == "5m"
    assert not CACHE_KEYS & model_settings(settings, "searcher").keys()


def test_prompt_cache_applies_when_claude_is_a_fallback(settings):
    settings.roles = Roles.model_validate({"planner": {"model": "openai:m", "fallbacks": ["claude:m"]}})
    assert CACHE_KEYS <= model_settings(settings, "planner").keys()


def test_prompt_cache_can_be_turned_off_or_lengthened(settings):
    settings.roles = Roles.model_validate({"planner": {"model": "claude:m"}})
    settings.models.prompt_cache = False
    assert model_settings(settings, "planner") == {}
    settings.models.prompt_cache = "1h"
    assert model_settings(settings, "planner")["anthropic_cache_tool_definitions"] == "1h"


def test_role_settings_pass_through_and_win(settings):
    thinking = {"type": "enabled", "budget_tokens": 4000}
    settings.roles = Roles.model_validate(
        {"planner": {"model": "claude:m", "settings": {"max_tokens": 8000, "anthropic_thinking": thinking}}}
    )
    out = model_settings(settings, "planner")
    assert out["max_tokens"] == 8000 and out["anthropic_thinking"] == thinking
    assert out["anthropic_cache"] == "5m"


def test_allowlist_accepts_claude_alias_either_way():
    check_allowed(RoleModel(model="claude:m"), BundleConfig(path=Path("."), allowed_providers=["anthropic"]))
    check_allowed(RoleModel(model="anthropic:m"), BundleConfig(path=Path("."), allowed_providers=["claude"]))
    with pytest.raises(ProviderNotAllowed):
        check_allowed(RoleModel(model="claude:m"), BundleConfig(path=Path("."), allowed_providers=["azure"]))


def test_missing_key_names_the_variable_never_the_value(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert missing_key("claude:m") == "ANTHROPIC_API_KEY"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    assert missing_key("claude:m") is None
    assert missing_key("ollama:m") is None


def test_brain_model_sets_every_role_and_role_vars_win(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAIN_BUNDLE", str(tmp_path))
    monkeypatch.setenv("BRAIN_MODEL", "claude:everyday")
    monkeypatch.setenv("BRAIN_JUDGE_MODEL", "openai:judge")
    for role in ("PLANNER", "SEARCHER", "WRITER"):
        monkeypatch.delenv(f"BRAIN_{role}_MODEL", raising=False)
    s = load_settings(tmp_path / "no-config")
    assert s.roles is not None
    assert s.roles.planner.model == "claude:everyday"
    assert s.roles.searcher is not None and s.roles.searcher.model == "claude:everyday"
    assert s.roles.judge is not None and s.roles.judge.model == "openai:judge"


def test_roles_yaml_models_section(monkeypatch, tmp_path):
    for role in ("", "PLANNER_", "SEARCHER_", "WRITER_", "JUDGE_"):
        monkeypatch.delenv(f"BRAIN_{role}MODEL", raising=False)
    monkeypatch.setenv("BRAIN_BUNDLE", str(tmp_path))
    (tmp_path / "roles.yaml").write_text(
        "models:\n  prompt_cache: '1h'\nroles:\n  planner:\n    model: claude:m\n    settings: {max_tokens: 4000}\n"
    )
    s = load_settings(tmp_path)
    assert s.models.prompt_cache == "1h"
    assert s.roles is not None and s.roles.planner.settings == {"max_tokens": 4000}


def test_agents_get_claude_settings(settings, monkeypatch):
    pytest.importorskip("pydantic_ai")
    from brain_harness.agent.loop import Harness

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")  # building the client needs one; nothing is sent
    settings.roles = Roles.model_validate({"planner": {"model": "claude:m"}})
    harness = Harness(settings)
    for agent in (harness.planner(), harness.searcher()):
        assert CACHE_KEYS <= dict(agent.model_settings or {}).keys()


def test_brain_models_command_flags_a_missing_key(monkeypatch, capsys):
    from brain_harness.apps.cli import main

    config = Path(__file__).resolve().parents[3] / "config"
    monkeypatch.delenv("BRAIN_BUNDLE", raising=False)
    monkeypatch.setenv("BRAIN_MODEL", "claude:m")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["--config", str(config), "models"]) == 1
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    assert main(["--config", str(config), "models"]) == 0
    assert "anthropic:m  (prompt cache 5m)" in capsys.readouterr().out
