"""Role -> model resolution.

Models are ``provider:model`` strings that Pydantic AI understands
(``anthropic:...``, ``openai:...``, ``azure:...``, ``google-gla:...``,
``bedrock:...``, ``ollama:...``). ``claude:`` is accepted as another name for
``anthropic:``. Point every role at a LiteLLM proxy with the ``openai:``
provider and ``OPENAI_BASE_URL`` if you want one gateway for keys, spend and
logging. Nothing here hard-codes a model; set them in ``config/roles.yaml``,
``BRAIN_MODEL`` or ``BRAIN_<ROLE>_MODEL``.
"""

from __future__ import annotations

import os
from typing import Any

from brain_harness.config import BundleConfig, RoleModel, Settings

# Provider aliases people type, mapped to the name Pydantic AI uses.
ALIASES = {"claude": "anthropic"}

# Environment variable each direct provider reads its key from. Used to say
# what is missing before a run, never to read or log the key itself.
KEY_ENV = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "azure": ("AZURE_OPENAI_API_KEY",),
    "google-gla": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
}


class ProviderNotAllowed(PermissionError):
    """The bundle's data policy does not allow this provider to see its content."""


def normalize(model: str) -> str:
    """``claude:x`` -> ``anthropic:x``; everything else unchanged."""
    if ":" not in model:
        return model
    provider, name = model.split(":", 1)
    return f"{ALIASES.get(provider, provider)}:{name}"


def provider_of(model: str) -> str:
    return normalize(model).split(":", 1)[0] if ":" in model else "unknown"


def is_claude(model: str) -> bool:
    """True for Claude on Anthropic's API (the only route here that takes Anthropic cache settings)."""
    return provider_of(model) == "anthropic"


def missing_key(model: str) -> str | None:
    """Name of the key variable a model needs and lacks, or None when set or not knowable."""
    names = KEY_ENV.get(provider_of(model))
    if not names or any(os.environ.get(n) for n in names):
        return None
    return names[0]


def check_allowed(role: RoleModel, bundle: BundleConfig) -> None:
    if not bundle.allowed_providers:
        return
    allowed = {ALIASES.get(p, p) for p in bundle.allowed_providers}
    for model in [role.model, *role.fallbacks]:
        provider = provider_of(model)
        if provider not in allowed:
            raise ProviderNotAllowed(f"{model!r} uses provider {provider!r}; bundle allows {bundle.allowed_providers}")


def role_model(settings: Settings, role: str) -> RoleModel:
    if settings.roles is None:
        raise ValueError("no models configured: add config/roles.yaml, or set BRAIN_MODEL")
    chosen: RoleModel = getattr(settings.roles, role, None) or settings.roles.planner
    return chosen


def model_settings(settings: Settings, role: str) -> dict[str, Any]:
    """Provider model settings for ``role``.

    For Claude, prompt caching is on by default: the instructions and tool
    schemas are identical on every turn of a search loop, and caching the
    growing conversation means each turn pays full price only for what is new.
    Keys are ``anthropic_``-prefixed, so other providers in a fallback chain
    ignore them. A role's own ``settings`` win over these defaults.
    """
    chosen = role_model(settings, role)
    out: dict[str, Any] = {}
    ttl = settings.models.prompt_cache
    if ttl and any(is_claude(m) for m in [chosen.model, *chosen.fallbacks]):
        out.update(
            anthropic_cache_instructions=ttl,
            anthropic_cache_tool_definitions=ttl,
            anthropic_cache=ttl,
        )
    out.update(chosen.settings)
    return out


def resolve(settings: Settings, role: str, bundle: BundleConfig) -> Any:
    """Return a Pydantic AI model (with fallbacks) for ``role``, after the provider check."""
    chosen = role_model(settings, role)
    check_allowed(chosen, bundle)
    primary = normalize(chosen.model)
    if not chosen.fallbacks:
        return primary
    from pydantic_ai.models import infer_model
    from pydantic_ai.models.fallback import FallbackModel

    return FallbackModel(infer_model(primary), *(infer_model(normalize(m)) for m in chosen.fallbacks))
