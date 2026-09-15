"""LangSmith tracing remains available after the native SDK migration."""

from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def _fake_langsmith_wrappers(**wrappers: object) -> dict[str, ModuleType]:
    package = ModuleType("langsmith")
    module = ModuleType("langsmith.wrappers")
    for name, wrapper in wrappers.items():
        setattr(module, name, wrapper)
    package.wrappers = module  # type: ignore[attr-defined]
    return {"langsmith": package, "langsmith.wrappers": module}


def test_openai_client_is_wrapped_when_langsmith_is_configured(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test")
    wrapped = object()
    raw_client = object()
    wrap = MagicMock(return_value=wrapped)
    with (
        patch(
            "nanobot.providers.langsmith_integration.importlib.util.find_spec",
            return_value=SimpleNamespace(),
        ),
        patch.dict(sys.modules, _fake_langsmith_wrappers(wrap_openai=wrap)),
        patch("nanobot.providers.openai_compat_provider.AsyncOpenAI", return_value=raw_client),
    ):
        provider = OpenAICompatProvider(api_key="sk-test")
        provider._build_client()

    assert provider._client is wrapped
    wrap.assert_called_once_with(raw_client)
    assert os.environ["LANGSMITH_TRACING"] == "true"


def test_anthropic_client_is_wrapped_when_langsmith_is_configured(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test")
    raw_client = object()
    wrapped = object()
    wrap = MagicMock(return_value=wrapped)
    with (
        patch(
            "nanobot.providers.langsmith_integration.importlib.util.find_spec",
            return_value=SimpleNamespace(),
        ),
        patch.dict(sys.modules, _fake_langsmith_wrappers(wrap_anthropic=wrap)),
        patch("anthropic.AsyncAnthropic", return_value=raw_client),
    ):
        provider = AnthropicProvider(api_key="sk-test")

    assert provider._client is wrapped
    wrap.assert_called_once_with(raw_client)


def test_missing_langsmith_keeps_native_client(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test")
    raw_client = MagicMock()
    with (
        patch(
            "nanobot.providers.langsmith_integration.importlib.util.find_spec",
            return_value=None,
        ),
        patch("nanobot.providers.openai_compat_provider.AsyncOpenAI", return_value=raw_client),
    ):
        provider = OpenAICompatProvider(api_key="sk-test")
        provider._build_client()

    assert provider._client is raw_client
