"""Declarative request API capabilities and automatic model defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import urlsplit

RequestAPI = Literal["chat_completions", "responses", "anthropic_messages"]
ProviderAPI = Literal[
    "chat_completions", "responses", "anthropic_messages", "bedrock_converse", "transcription",
]


def is_direct_openai_base(api_base: str | None) -> bool:
    """Return whether the endpoint matches the direct OpenAI routing rule."""
    if not api_base:
        return True
    normalized = api_base.strip().lower().rstrip("/")
    return "api.openai.com" in normalized and "openrouter" not in normalized


def _api_base_identity(api_base: str) -> tuple[str, str | None, int | None, str]:
    """Normalize an endpoint's origin and optional OpenAI-compatible /v1 suffix."""
    parsed = urlsplit(api_base.strip())
    port = parsed.port
    return (
        parsed.scheme,
        parsed.hostname,
        port if port is not None else {"http": 80, "https": 443}.get(parsed.scheme),
        parsed.path.rstrip("/").removesuffix("/v1"),
    )


def is_hosted_web_search_type(value: object) -> bool:
    return isinstance(value, str) and (
        value == "web_search" or value.startswith("web_search_")
    )


def is_hosted_web_search_tool(tool: object) -> bool:
    if not isinstance(tool, dict):
        return False
    return is_hosted_web_search_type(cast(dict[object, object], tool).get("type"))


def hosted_web_search_enabled(
    extra_body: dict[str, Any], default_tools: tuple[str, ...] = (),
) -> bool:
    if "tools" in extra_body:
        tools = extra_body["tools"]
        return isinstance(tools, list) and any(
            is_hosted_web_search_tool(tool) for tool in cast(list[object], tools)
        )
    return any(is_hosted_web_search_type(value) for value in default_tools)


@dataclass(frozen=True)
class ModelAPICapabilities:
    """APIs declared for one model, including its preferred request surface."""

    supported_apis: tuple[RequestAPI, ...] = ("chat_completions",)
    preferred_api: RequestAPI = "chat_completions"


@dataclass(frozen=True)
class ResponsesCapabilities:
    """Provider capabilities for the shared OpenAI Responses execution path.

    ``reasoning_replay`` selects whether multi-turn reasoning is retained as
    encrypted server content, plaintext local history, or not requested.
    ``endpoint_models`` limits automatic model rules to named API bases;
    ``models`` applies those rules regardless of the configured endpoint.
    """

    models: tuple[str, ...] = ()
    model_prefixes: tuple[str, ...] = ()
    route_reasoning: bool = False
    requires_direct_openai_base: bool = False
    reasoning_replay: Literal["none", "encrypted", "plaintext"] = "none"
    supports_native_compaction: bool = False
    allows_chat_fallback: bool = True
    endpoint_models: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def matches_model(self, model: str, *, api_base: str | None = None) -> bool:
        """Match curated models, restricting endpoint defaults when a base is supplied."""
        model_name = model.lower()
        wire_name = model_name.rsplit("/", 1)[-1]
        supported_models = self.models + tuple(
            model_id
            for base, models in self.endpoint_models
            if api_base is None or _api_base_identity(api_base) == _api_base_identity(base)
            for model_id in models
        )
        return any(
            model_name == supported.lower()
            or model_name.endswith(f"/{supported.lower()}")
            for supported in supported_models
        ) or any(wire_name.startswith(prefix.lower()) for prefix in self.model_prefixes)

    def model_api(
        self, model: str, reasoning_effort: str | None = None,
        *, api_base: str | None = None,
    ) -> ModelAPICapabilities:
        """Resolve the provider's curated API defaults for one model."""
        if not self.matches_model(model, api_base=api_base) and not (
            self.route_reasoning and reasoning_effort and reasoning_effort.lower() != "none"
        ):
            return ModelAPICapabilities()
        apis: tuple[RequestAPI, ...] = (
            ("responses", "chat_completions") if self.allows_chat_fallback else ("responses",)
        )
        return ModelAPICapabilities(supported_apis=apis, preferred_api="responses")

    def default_model_api(
        self,
        model: str,
        reasoning_effort: str | None = None,
        *,
        api_base: str | None = None,
        default_api_base: str = "",
        extra_body: dict[str, Any] | None = None,
        default_tools: tuple[str, ...] = (),
    ) -> ModelAPICapabilities:
        """Apply endpoint, reasoning, and hosted-tool rules to automatic selection."""
        body = extra_body or {}
        effective_base = api_base or default_api_base or None
        # Explicit hosted tools require Responses; defaults follow the endpoint's model rules.
        search_model_base = None if hosted_web_search_enabled(body) else effective_base
        if hosted_web_search_enabled(body, default_tools) and (
            self.route_reasoning or self.matches_model(model, api_base=search_model_base)
        ):
            return ModelAPICapabilities(("responses",), "responses")
        if self.requires_direct_openai_base and not is_direct_openai_base(api_base):
            return ModelAPICapabilities()
        return self.model_api(model, reasoning_effort, api_base=effective_base)
