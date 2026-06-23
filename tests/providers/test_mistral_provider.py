"""Tests for the Mistral provider registration and reasoning quirks."""

from __future__ import annotations

from unittest.mock import patch

from blackcat.config.schema import ProvidersConfig
from blackcat.providers.openai_compat_provider import OpenAICompatProvider
from blackcat.providers.registry import PROVIDERS, find_by_name


def _mistral_provider(default_model: str = "mistral-medium-3-5") -> OpenAICompatProvider:
    spec = find_by_name("mistral")
    assert spec is not None
    with patch("blackcat.providers.openai_compat_provider.AsyncOpenAI"):
        return OpenAICompatProvider(
            api_key="test-key",
            default_model=default_model,
            spec=spec,
        )


def test_mistral_config_field_exists() -> None:
    """ProvidersConfig should have a mistral field."""
    config = ProvidersConfig()
    assert hasattr(config, "mistral")


def test_mistral_provider_in_registry() -> None:
    """Mistral should be registered in the provider registry."""
    specs = {s.name: s for s in PROVIDERS}
    assert "mistral" in specs

    mistral = specs["mistral"]
    assert mistral.env_key == "MISTRAL_API_KEY"
    assert mistral.default_api_base == "https://api.mistral.ai/v1"


def test_mistral_keyword_match_covers_model_families() -> None:
    """Codestral, Devstral, Ministral, Magistral models route to the Mistral spec."""
    from blackcat.config.schema import Config

    for model in (
        "mistral-large-latest",
        "magistral-medium-latest",
        "ministral-8b-latest",
        "codestral-latest",
        "devstral-medium-latest",
    ):
        config = Config.model_validate({
            "providers": {"mistral": {"apiKey": "test-key"}},
            "agents": {"defaults": {"model": model}},
        })
        assert config.get_provider_name(model) == "mistral", model


def test_reasoning_effort_low_remaps_to_none_omitted() -> None:
    """Mistral rejects low/medium efforts: low should map to "none" (omitted)."""
    p = _mistral_provider()
    kwargs = p._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="mistral-medium-3-5",
        max_tokens=64,
        temperature=0.5,
        reasoning_effort="low",
        tool_choice=None,
    )
    assert "reasoning_effort" not in kwargs


def test_reasoning_effort_minimal_remaps_to_none_omitted() -> None:
    p = _mistral_provider()
    kwargs = p._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="mistral-vibe-cli-latest",
        max_tokens=64,
        temperature=0.5,
        reasoning_effort="minimal",
        tool_choice=None,
    )
    assert "reasoning_effort" not in kwargs


def test_reasoning_effort_medium_remaps_to_high() -> None:
    """Mistral has no 'medium' tier: bump up to 'high'."""
    p = _mistral_provider()
    kwargs = p._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="mistral-medium-3-5",
        max_tokens=64,
        temperature=0.5,
        reasoning_effort="medium",
        tool_choice=None,
    )
    assert kwargs["reasoning_effort"] == "high"


def test_reasoning_effort_high_passes_through() -> None:
    p = _mistral_provider()
    kwargs = p._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="mistral-medium-3-5",
        max_tokens=64,
        temperature=0.5,
        reasoning_effort="high",
        tool_choice=None,
    )
    assert kwargs["reasoning_effort"] == "high"


def test_magistral_strips_reasoning_effort() -> None:
    """Magistral reasons implicitly; API rejects reasoning_effort kwarg."""
    p = _mistral_provider()
    for effort in ("low", "medium", "high", "minimal"):
        kwargs = p._build_kwargs(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            model="magistral-medium-latest",
            max_tokens=64,
            temperature=0.5,
            reasoning_effort=effort,
            tool_choice=None,
        )
        assert "reasoning_effort" not in kwargs, effort


def test_extract_thinking_content_from_mistral_response() -> None:
    """Thinking blocks should land in reasoning_content, not content."""
    p = _mistral_provider()
    response = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": [
                                {"type": "text", "text": "Let me think..."}
                            ],
                            "closed": True,
                        },
                        {"type": "text", "text": "Final answer is 35."},
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    parsed = p._parse(response)
    assert parsed.content == "Final answer is 35."
    assert parsed.reasoning_content == "Let me think..."


def test_extract_thinking_content_with_tool_calls() -> None:
    """A response with thinking + tool_calls (no text content) should still parse."""
    p = _mistral_provider()
    response = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "abc123def",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city": "Paris"}',
                            },
                        }
                    ],
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": [
                                {"type": "text", "text": "I should call get_weather."}
                            ],
                        }
                    ],
                },
            }
        ],
    }
    parsed = p._parse(response)
    assert parsed.content in (None, "")
    assert parsed.reasoning_content == "I should call get_weather."
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].name == "get_weather"
    assert parsed.tool_calls[0].arguments == {"city": "Paris"}


def test_thinking_content_only_for_mistral_spec() -> None:
    """Providers without extract_thinking_blocks should not lift thinking text."""
    other_spec = find_by_name("openai")
    assert other_spec is not None
    with patch("blackcat.providers.openai_compat_provider.AsyncOpenAI"):
        p = OpenAICompatProvider(
            api_key="test-key",
            default_model="gpt-4o",
            spec=other_spec,
        )

    response = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": [{"type": "text", "text": "secret"}],
                        },
                        {"type": "text", "text": "hi"},
                    ],
                },
            }
        ],
    }
    parsed = p._parse(response)
    assert parsed.content == "hi"
    assert parsed.reasoning_content is None


def test_streaming_thinking_chunks_become_reasoning() -> None:
    """Streamed thinking deltas (Mistral shape) feed reasoning_content."""
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": [{"type": "text", "text": "step 1 "}],
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": [{"type": "text", "text": "step 2"}],
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"content": "final"},
                    "finish_reason": "stop",
                }
            ]
        },
    ]
    parsed = OpenAICompatProvider._parse_chunks(chunks)
    assert parsed.content == "final"
    assert parsed.reasoning_content == "step 1 step 2"


def test_streaming_thinking_chunks_via_sdk_path() -> None:
    """The SDK-style branch must coerce list-shaped delta.content to text.

    Regression: Mistral's vibe-cli/medium-3-5 streamed delta.content as a
    list, which was previously appended verbatim to content_parts and blew
    up later with "can only concatenate str (not list) to str".
    """

    class _Delta:
        def __init__(self, content):
            self.content = content
            self.tool_calls = None
            self.function_call = None

    class _Choice:
        def __init__(self, content, finish=None):
            self.delta = _Delta(content)
            self.finish_reason = finish

    class _Chunk:
        def __init__(self, content, finish=None):
            self.choices = [_Choice(content, finish)]

    chunks = [
        _Chunk([{"type": "thinking", "thinking": [{"type": "text", "text": "ponder"}]}]),
        _Chunk([{"type": "text", "text": "Hello "}]),
        _Chunk("world.", finish="stop"),
    ]
    parsed = OpenAICompatProvider._parse_chunks(chunks)
    assert parsed.content == "Hello world."
    assert parsed.reasoning_content == "ponder"


def test_mistral_strips_reasoning_content_from_history() -> None:
    """Mistral's request schema 400s on reasoning_content; it must be dropped."""
    p = _mistral_provider()
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "Hello!",
            "reasoning_content": "internal thoughts",
        },
        {"role": "user", "content": "follow up"},
    ]
    sanitized = p._sanitize_messages(messages)
    assert all("reasoning_content" not in msg for msg in sanitized)
    assert sanitized[1]["content"] == "Hello!"


def test_mistral_tool_call_ids_get_normalized() -> None:
    """Non-9-char tool_call IDs should be hashed to 9-char alphanumeric."""
    p = _mistral_provider()
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_abc_xyz_too_long_for_mistral",
                    "type": "function",
                    "function": {"name": "x", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_abc_xyz_too_long_for_mistral",
            "content": "ok",
        },
    ]
    sanitized = p._sanitize_messages(messages)
    assistant_id = sanitized[1]["tool_calls"][0]["id"]
    tool_id = sanitized[2]["tool_call_id"]
    assert len(assistant_id) == 9
    assert assistant_id.isalnum()
    assert assistant_id == tool_id
