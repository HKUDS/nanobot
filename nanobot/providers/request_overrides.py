"""Resolve per-model request differences without changing shared connections."""

from copy import deepcopy

from nanobot.config.schema import ModelPresetConfig, ProviderConfig, RequestOverrides


def isolate_request_overrides(
    candidate: ModelPresetConfig, *, previous_provider: str | None, provider: str | None,
) -> ModelPresetConfig:
    """Keep inherited request settings only within the same configured connection."""
    if previous_provider is not None and previous_provider == provider:
        return candidate
    return candidate.model_copy(update={
        "extra_headers": None, "extra_query": None, "extra_body": None,
    })


def request_override_fields(backend: str) -> tuple[str, ...]:
    if backend in {"openai_compat", "anthropic"}:
        return ("extra_headers", "extra_query", "extra_body")
    if backend in {"openai_codex", "xai_grok", "bedrock"}:
        return ("extra_body",)
    return ()


def apply_request_overrides(
    connection: ProviderConfig | None, overrides: RequestOverrides,
) -> ProviderConfig | None:
    """Overlay keys on a detached snapshot; nested body values replace as a unit.

    Headers match without case sensitivity. Query and body keys are exact.
    None and empty maps inherit; JSON null inside a body remains a literal value.
    Adapter-specific request assembly still runs after this configuration merge.
    """
    if not any((overrides.extra_headers, overrides.extra_query, overrides.extra_body)):
        return connection.model_copy(deep=True) if connection is not None else None
    result = connection.model_copy(deep=True) if connection is not None else ProviderConfig()
    for field in ("extra_headers", "extra_query", "extra_body"):
        values = getattr(overrides, field)
        if not values:
            continue
        merged = dict(getattr(result, field) or {})
        if field == "extra_headers":
            names = {key.lower() for key in values}
            merged = {key: value for key, value in merged.items() if key.lower() not in names}
        merged.update(deepcopy(values))
        setattr(result, field, merged)
    return result
