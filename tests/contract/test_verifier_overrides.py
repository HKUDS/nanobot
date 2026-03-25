"""Tests for AnswerVerifier per-call model/temperature overrides."""

from __future__ import annotations

import pytest

from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider


@pytest.mark.asyncio
async def test_verifier_verify_uses_override_model():
    """AnswerVerifier.verify() passes override model to provider."""
    from nanobot.agent.verifier import AnswerVerifier

    provider = ScriptedProvider(
        [
            LLMResponse(content='{"confidence": 5, "issues": []}'),
        ]
    )
    verifier = AnswerVerifier(
        provider=provider,
        model="default-model",
        temperature=0.7,
        max_tokens=4096,
        verification_mode="always",
        memory_uncertainty_threshold=0.5,
    )
    await verifier.verify(
        "question?",
        "answer",
        [],
        model="override-model",
        temperature=0.2,
    )
    assert provider.call_log[0]["model"] == "override-model"


@pytest.mark.asyncio
async def test_verifier_verify_uses_defaults_when_no_override():
    """AnswerVerifier.verify() uses construction-time defaults when no override."""
    from nanobot.agent.verifier import AnswerVerifier

    provider = ScriptedProvider(
        [
            LLMResponse(content='{"confidence": 5, "issues": []}'),
        ]
    )
    verifier = AnswerVerifier(
        provider=provider,
        model="default-model",
        temperature=0.7,
        max_tokens=4096,
        verification_mode="always",
        memory_uncertainty_threshold=0.5,
    )
    await verifier.verify("question?", "answer", [])
    assert provider.call_log[0]["model"] == "default-model"


@pytest.mark.asyncio
async def test_verifier_recovery_uses_override_model():
    """AnswerVerifier.attempt_recovery() passes override model to provider."""
    from nanobot.agent.verifier import AnswerVerifier

    provider = ScriptedProvider([LLMResponse(content="recovered")])
    verifier = AnswerVerifier(
        provider=provider,
        model="default-model",
        temperature=0.7,
        max_tokens=4096,
        verification_mode="off",
        memory_uncertainty_threshold=0.5,
    )
    await verifier.attempt_recovery(
        channel="test",
        chat_id="test",
        all_msgs=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "question?"},
        ],
        model="override-model",
        temperature=0.2,
    )
    assert provider.call_log[0]["model"] == "override-model"
