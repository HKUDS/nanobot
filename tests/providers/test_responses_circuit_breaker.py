"""Tests for Responses API circuit breaker in OpenAICompatProvider."""

import time

import pytest

from nanobot.providers.base import ProviderCallContext
from nanobot.providers.openai_compat_provider import (
    _RESPONSES_FAILURE_THRESHOLD,
    _RESPONSES_PROBE_INTERVAL_S,
    OpenAICompatProvider,
)
from nanobot.providers.openai_responses.state import build_responses_state


@pytest.fixture()
def provider():
    """A direct-OpenAI provider with Responses API support."""
    p = OpenAICompatProvider.__new__(OpenAICompatProvider)
    p.default_model = "gpt-5"
    p._spec = type("Spec", (), {"name": "openai"})()
    p._effective_base = "https://api.openai.com/v1"
    p._api_type = "auto"
    p._responses_failures = {}
    p._responses_tripped_at = {}
    return p


def test_responses_api_available_by_default(provider):
    assert provider._should_use_responses_api("gpt-5", None) is True


def test_deepseek_v4_flash_uses_responses_by_model(provider):
    provider._spec = type("Spec", (), {
        "name": "deepseek",
        "responses_models": ("deepseek-v4-flash",),
        "strip_model_prefix": False,
        "strip_model_prefixes": (),
    })()
    provider._effective_base = "https://api.deepseek.com"
    provider.default_model = "deepseek-v4-flash"

    assert provider._should_use_responses_api("deepseek-v4-flash", None) is True
    assert provider._should_use_responses_api("deepseek-v4-pro", None) is False


def test_deepseek_v4_flash_matches_provider_prefixed_model(provider):
    provider._spec = type("Spec", (), {
        "name": "deepseek",
        "responses_models": ("deepseek-v4-flash",),
        "strip_model_prefix": False,
        "strip_model_prefixes": (),
    })()
    provider._effective_base = "https://api.deepseek.com"

    assert provider._should_use_responses_api("deepseek/deepseek-v4-flash", None) is True


def test_direct_openai_enables_server_compaction(provider):
    provider._extra_body = {}

    body = provider._build_responses_body(
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        model="gpt-5.6",
        max_tokens=30_000,
        temperature=0.1,
        reasoning_effort="high",
        tool_choice=None,
        provider_context=ProviderCallContext(context_window_tokens=100_000),
    )

    assert body["context_management"] == [{
        "type": "compaction",
        "compact_threshold": 70_000,
    }]


def test_api_type_chat_completions_disables_responses(provider):
    provider._api_type = "chat_completions"
    assert provider._should_use_responses_api("gpt-5", None) is False


def test_api_type_responses_forces_responses_for_openai(provider):
    provider.default_model = "gpt-4o"
    provider._api_type = "responses"
    assert provider._should_use_responses_api("gpt-4o", None) is True


def test_api_type_responses_ignores_circuit_breaker(provider):
    provider.default_model = "gpt-4o"
    provider._api_type = "responses"
    provider._responses_failures = {"gpt-4o|gpt-4o|": _RESPONSES_FAILURE_THRESHOLD}
    provider._responses_tripped_at = {"gpt-4o|gpt-4o|": 0.0}

    assert provider._should_use_responses_api("gpt-4o", None) is True


def test_api_type_responses_does_not_force_non_openai(provider):
    provider._spec = type("Spec", (), {"name": "custom"})()
    provider._api_type = "responses"

    assert provider._should_use_responses_api("gpt-4o", None) is False


def test_circuit_opens_after_threshold(provider):
    for _ in range(_RESPONSES_FAILURE_THRESHOLD):
        provider._record_responses_failure("gpt-5", None)
    assert provider._should_use_responses_api("gpt-5", None) is False


def test_circuit_does_not_affect_other_models(provider):
    for _ in range(_RESPONSES_FAILURE_THRESHOLD):
        provider._record_responses_failure("gpt-5", None)
    assert provider._should_use_responses_api("o4-mini", None) is True


def test_success_resets_circuit(provider):
    for _ in range(_RESPONSES_FAILURE_THRESHOLD):
        provider._record_responses_failure("gpt-5", None)
    assert provider._should_use_responses_api("gpt-5", None) is False
    provider._record_responses_success("gpt-5", None)
    assert provider._should_use_responses_api("gpt-5", None) is True


def test_probe_after_interval(provider, monkeypatch):
    for _ in range(_RESPONSES_FAILURE_THRESHOLD):
        provider._record_responses_failure("gpt-5", None)
    assert provider._should_use_responses_api("gpt-5", None) is False

    # Fast-forward past the probe interval
    key = "gpt-5:"
    provider._responses_tripped_at[key] = time.monotonic() - _RESPONSES_PROBE_INTERVAL_S - 1
    assert provider._should_use_responses_api("gpt-5", None) is True


def test_below_threshold_still_allows(provider):
    provider._record_responses_failure("gpt-5", None)
    provider._record_responses_failure("gpt-5", None)
    assert provider._should_use_responses_api("gpt-5", None) is True


def test_reasoning_effort_keyed_separately(provider):
    for _ in range(_RESPONSES_FAILURE_THRESHOLD):
        provider._record_responses_failure("o3", "high")
    assert provider._should_use_responses_api("o3", "high") is False
    assert provider._should_use_responses_api("o3", "low") is True


def test_reasoning_effort_key_is_case_insensitive(provider):
    for _ in range(_RESPONSES_FAILURE_THRESHOLD):
        provider._record_responses_failure("o3", "High")
    assert provider._should_use_responses_api("o3", "high") is False


# ======================================================================
# _should_fallback_from_responses_error
# ======================================================================


class _FakeAPIError(Exception):
    def __init__(self, status_code, body):
        super().__init__(str(body))
        self.status_code = status_code
        self.body = body
        self.response = None


def test_serde_deserialize_error_does_not_trigger_fallback():
    # Serde errors can also identify malformed user-provided request fields.
    # The known DeepSeek wire-shape bug is fixed at serialization time instead.
    err = _FakeAPIError(400, {
        "message": (
            "Failed to deserialize the JSON body into the target type: "
            "input: invalid type: string \"Michael topped up DeepSeek ...\", "
            "expected a sequence at line 1 column 268612"
        ),
        "type": "invalid_request_error",
        "param": None,
    })
    assert OpenAICompatProvider._should_fallback_from_responses_error(err) is False


def test_legacy_compatibility_markers_still_trigger_fallback():
    err = _FakeAPIError(400, "parameter `instructions` is unsupported")
    assert OpenAICompatProvider._should_fallback_from_responses_error(err) is True


# ======================================================================
# DeepSeek Responses wire shape (PR #5214 root cause)
# ======================================================================


def _deepseek_provider(provider):
    provider._spec = type("Spec", (), {
        "name": "deepseek",
        "responses_models": ("deepseek-v4-flash",),
        "strip_model_prefix": False,
        "strip_model_prefixes": (),
    })()
    provider._effective_base = "https://api.deepseek.com"
    provider.default_model = "deepseek-v4-flash"
    provider._extra_body = {}
    return provider


def test_deepseek_full_history_body_keeps_reasoning_content_as_array(provider):
    # Full-history fixture: DeepSeek's Responses gateway rejects reasoning
    # items whose ``content`` is a plain string ("input: invalid type: string
    # ..., expected a sequence"); the wire body must keep it as a part list.
    _deepseek_provider(provider)

    body = provider._build_responses_body(
        messages=[
            {
                "role": "assistant",
                "reasoning_content": "Michael topped up DeepSeek with $10.",
                "content": "All systems aligned now.",
            },
            {"role": "user", "content": "audit the custom tools"},
        ],
        tools=None,
        model="deepseek-v4-flash",
        max_tokens=1000,
        temperature=0.1,
        reasoning_effort=None,
        tool_choice=None,
    )

    reasoning_items = [item for item in body["input"] if item.get("type") == "reasoning"]
    assert len(reasoning_items) == 1
    assert reasoning_items[0]["content"] == [
        {"type": "output_text", "text": "Michael topped up DeepSeek with $10."},
    ]


def test_deepseek_replay_body_keeps_reasoning_content_as_array(provider):
    # Replay/consolidation fixture: after token consolidation clears
    # provider_state the next turn converts full history on top of the
    # replayed prior items. Both replayed and converted reasoning items must
    # keep list content on the wire.
    _deepseek_provider(provider)

    prior_items = [
        {
            "type": "reasoning",
            "id": "rs_1",
            "content": [{"type": "output_text", "text": "prior reasoning"}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "prior answer"}],
            "status": "completed",
            "id": "msg_0",
        },
    ]
    state = build_responses_state(
        provider=provider._responses_state_provider(),
        model="deepseek-v4-flash",
        input_items=prior_items,
        output_items=[],
    ).with_pending_messages([
        {
            "role": "assistant",
            "reasoning_content": "think first",
            "content": "answer",
        },
        {"role": "user", "content": "audit the custom tools"},
    ])

    body = provider._build_responses_body(
        messages=[
            {"role": "system", "content": "You are KITT."},
            {"role": "user", "content": "audit the custom tools"},
        ],
        tools=None,
        model="deepseek-v4-flash",
        max_tokens=1000,
        temperature=0.1,
        reasoning_effort=None,
        tool_choice=None,
        provider_context=ProviderCallContext(conversation_state=state),
    )

    reasoning_items = [item for item in body["input"] if item.get("type") == "reasoning"]
    assert len(reasoning_items) == 2  # one replayed from state, one converted
    for item in reasoning_items:
        assert isinstance(item["content"], list)
        assert item["content"][0]["type"] == "output_text"
