"""Role -> model resolution.

Models are ``provider:model`` strings that Pydantic AI understands
(``anthropic:...``, ``openai:...``, ``azure:...``, ``google-gla:...``,
``bedrock:...``, ``ollama:...``). Point every role at a LiteLLM proxy with the
``openai:`` provider and ``OPENAI_BASE_URL`` if you want one gateway for keys,
spend and logging. Nothing here hard-codes a model; set them in
``config/roles.yaml`` or ``BRAIN_<ROLE>_MODEL``.
"""

from __future__ import annotations

from typing import Any

from brain_harness.config import BundleConfig, RoleModel, Settings


class ProviderNotAllowed(PermissionError):
    """The bundle's data policy does not allow this provider to see its content."""


def provider_of(model: str) -> str:
    return model.split(":", 1)[0] if ":" in model else "unknown"


def check_allowed(role: RoleModel, bundle: BundleConfig) -> None:
    if not bundle.allowed_providers:
        return
    for model in [role.model, *role.fallbacks]:
        provider = provider_of(model)
        if provider not in bundle.allowed_providers:
            raise ProviderNotAllowed(f"{model!r} uses provider {provider!r}; bundle allows {bundle.allowed_providers}")


def role_model(settings: Settings, role: str) -> RoleModel:
    if settings.roles is None:
        raise ValueError("no models configured: add config/roles.yaml or set BRAIN_PLANNER_MODEL")
    chosen = getattr(settings.roles, role, None) or settings.roles.planner
    return chosen


def resolve(settings: Settings, role: str, bundle: BundleConfig) -> Any:
    """Return a Pydantic AI model (with fallbacks) for ``role``, after the provider check."""
    chosen = role_model(settings, role)
    check_allowed(chosen, bundle)
    if not chosen.fallbacks:
        return chosen.model
    from pydantic_ai.models import infer_model
    from pydantic_ai.models.fallback import FallbackModel

    return FallbackModel(infer_model(chosen.model), *(infer_model(m) for m in chosen.fallbacks))
