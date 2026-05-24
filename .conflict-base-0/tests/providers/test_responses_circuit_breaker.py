"""Tests for Responses API circuit breaker in OpenAICompatProvider."""

import time

import pytest

from nanobot.providers.openai_compat_provider import (
    OpenAICompatProvider,
    _RESPONSES_FAILURE_THRESHOLD,
    _RESPONSES_PROBE_INTERVAL_S,
)


@pytest.fixture()
def provider():
    """A direct-OpenAI provider with Responses API support."""
    p = OpenAICompatProvider.__new__(OpenAICompatProvider)
    p.default_model = "gpt-5"
    p._spec = type("Spec", (), {"name": "openai"})()
    p._effective_base = "https://api.openai.com/v1"
    p._responses_failures = {}
    p._responses_tripped_at = {}
    return p


def test_responses_api_available_by_default(provider):
    assert provider._should_use_responses_api("gpt-5", None) is True


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
