"""Harness configuration.

Loaded from YAML files under ``config/`` (or paths in ``BRAIN_CONFIG_DIR``) with
environment overrides. Models are named per role so each can be swapped
independently; nothing here imports a provider SDK.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class RoleModel(BaseModel):
    """A role's model plus optional fallbacks, as provider:model strings."""

    model: str
    fallbacks: list[str] = Field(default_factory=list)


class Roles(BaseModel):
    planner: RoleModel
    searcher: RoleModel
    writer: RoleModel | None = None
    judge: RoleModel | None = None


class Caps(BaseModel):
    """Hard caps on what a single tool call may return (see design doc, Tools)."""

    grep_matches: int = 100
    glob_paths: int = 100
    list_entries: int = 200
    read_lines: int = 2000
    read_line_chars: int = 2000
    link_edges: int = 100
    search_pages: int = 20
    tool_output_tokens: int = 10_000


class Budgets(BaseModel):
    """Per-run limits, enforced in the loop rather than the prompt."""

    max_requests: int = 40
    max_tool_calls: int = 150
    max_total_tokens: int = 400_000
    max_cost_usd: float = 2.0
    repeat_call_limit: int = 3
    collapse_after_turns: int = 3
    compact_at_fraction: float = 0.7
    max_parallel_searchers: int = 6
    context_window_tokens: int = 200_000
    model_retries: int = 2


class BundleConfig(BaseModel):
    path: Path
    description: str | None = None
    # Providers allowed to see this bundle's content, e.g. ["anthropic", "azure"].
    # Empty means any configured provider.
    allowed_providers: list[str] = Field(default_factory=list)
    # Writes go to a new git branch for review, never to the checked-out branch.
    writes_enabled: bool = False


class Settings(BaseModel):
    bundles: dict[str, BundleConfig]
    default_bundle: str
    roles: Roles | None = None
    caps: Caps = Field(default_factory=Caps)
    budgets: Budgets = Field(default_factory=Budgets)
    scratch_dir: Path = Path(".brain/scratch")
    run_log_dir: Path = Path(".brain/runs")
    producer_id: str = "brain-harness/0.1.0"

    def bundle(self, name: str | None = None) -> BundleConfig:
        key = name or self.default_bundle
        if key not in self.bundles:
            raise KeyError(f"unknown bundle {key!r}; configured: {sorted(self.bundles)}")
        return self.bundles[key]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a mapping")
    return data


def load_settings(config_dir: str | os.PathLike[str] | None = None) -> Settings:
    """Merge ``bundles.yaml``, ``roles.yaml`` and ``budgets.yaml`` from ``config_dir``.

    Environment overrides: ``BRAIN_BUNDLE`` (path of a single default bundle),
    ``BRAIN_PLANNER_MODEL``, ``BRAIN_SEARCHER_MODEL``, ``BRAIN_WRITER_MODEL``,
    ``BRAIN_JUDGE_MODEL``.
    """
    base = Path(config_dir or os.environ.get("BRAIN_CONFIG_DIR", "config"))
    data: dict[str, Any] = {}
    data.update(_read_yaml(base / "bundles.yaml"))
    roles = _read_yaml(base / "roles.yaml")
    if roles:
        data["roles"] = roles.get("roles", roles)
    budgets = _read_yaml(base / "budgets.yaml")
    if budgets:
        data["caps"] = budgets.get("caps", {})
        data["budgets"] = budgets.get("budgets", {})

    if env_bundle := os.environ.get("BRAIN_BUNDLE"):
        data["bundles"] = {"default": {"path": env_bundle}}
        data["default_bundle"] = "default"

    env_roles = {
        role: os.environ[f"BRAIN_{role.upper()}_MODEL"]
        for role in ("planner", "searcher", "writer", "judge")
        if os.environ.get(f"BRAIN_{role.upper()}_MODEL")
    }
    if env_roles:
        merged = dict(data.get("roles") or {})
        for role, model in env_roles.items():
            merged[role] = {"model": model}
        data["roles"] = merged

    if "bundles" not in data:
        raise ValueError("no bundles configured: add config/bundles.yaml or set BRAIN_BUNDLE")
    data.setdefault("default_bundle", next(iter(data["bundles"])))
    return Settings.model_validate(data)
