"""Tests for EndpointPool — round-robin rotation with cooldown failover.

Imports base.py and endpoint_pool.py directly (not through __init__.py)
to avoid pulling in heavy dependencies like litellm.
"""

import importlib
import time

import pytest

# Import the two modules we actually need, bypassing the package __init__.py
# which eagerly imports providers that need litellm, oauth_cli_kit, etc.
_base = importlib.import_module("nanobot.providers.base")
_pool = importlib.import_module("nanobot.providers.endpoint_pool")

LLMProvider = _base.LLMProvider
LLMResponse = _base.LLMResponse
EndpointPool = _pool.EndpointPool


class ScriptedProvider(LLMProvider):
    """Provider that returns pre-scripted responses in order."""

    def __init__(self, responses, name=""):
        super().__init__()
        self._responses = list(responses)
        self._name = name
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get_default_model(self) -> str:
        return f"test-model-{self._name}"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_empty_endpoints_raises():
    with pytest.raises(ValueError, match="at least one"):
        EndpointPool([])


def test_single_endpoint_works():
    pool = EndpointPool([ScriptedProvider([LLMResponse(content="ok")])])
    assert pool.get_default_model() == "test-model-"


# ---------------------------------------------------------------------------
# Basic rotation — first endpoint succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_on_first_endpoint():
    ep0 = ScriptedProvider([LLMResponse(content="from-0")], name="0")
    ep1 = ScriptedProvider([LLMResponse(content="from-1")], name="1")
    pool = EndpointPool([ep0, ep1])

    resp = await pool.chat(messages=[])
    assert resp.content == "from-0"
    assert ep0.calls == 1
    assert ep1.calls == 0


# ---------------------------------------------------------------------------
# Failover — first endpoint fails, second succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failover_to_second_endpoint():
    ep0 = ScriptedProvider(
        [LLMResponse(content="429 rate limit", finish_reason="error")], name="0"
    )
    ep1 = ScriptedProvider([LLMResponse(content="from-1")], name="1")
    pool = EndpointPool([ep0, ep1], cooldown_seconds=60)

    resp = await pool.chat(messages=[])
    assert resp.content == "from-1"
    assert ep0.calls == 1
    assert ep1.calls == 1


# ---------------------------------------------------------------------------
# Failover — exception from provider is caught
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failover_on_exception():
    # "connection refused" contains "connection" which is a transient error marker
    ep0 = ScriptedProvider([ConnectionError("connection refused")], name="0")
    ep1 = ScriptedProvider([LLMResponse(content="from-1")], name="1")
    pool = EndpointPool([ep0, ep1], cooldown_seconds=60)

    resp = await pool.chat(messages=[])
    assert resp.content == "from-1"


# ---------------------------------------------------------------------------
# All endpoints fail — returns last error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_endpoints_fail_returns_last_error():
    ep0 = ScriptedProvider(
        [LLMResponse(content="429 rate limit", finish_reason="error")], name="0"
    )
    ep1 = ScriptedProvider(
        [LLMResponse(content="503 server error", finish_reason="error")], name="1"
    )
    pool = EndpointPool([ep0, ep1])

    resp = await pool.chat(messages=[])
    assert resp.finish_reason == "error"
    assert "503" in resp.content
    assert ep0.calls == 1
    assert ep1.calls == 1


# ---------------------------------------------------------------------------
# Non-transient error — no failover, returns immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_transient_error_no_failover():
    ep0 = ScriptedProvider(
        [LLMResponse(content="401 unauthorized", finish_reason="error")], name="0"
    )
    ep1 = ScriptedProvider([LLMResponse(content="from-1")], name="1")
    pool = EndpointPool([ep0, ep1])

    resp = await pool.chat(messages=[])
    assert resp.content == "401 unauthorized"
    # Non-transient error — should NOT try ep1.
    assert ep1.calls == 0


# ---------------------------------------------------------------------------
# Cooldown — failed endpoint is skipped on next call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cooldown_skips_failed_endpoint():
    ep0 = ScriptedProvider(
        [
            LLMResponse(content="429 rate limit", finish_reason="error"),
            LLMResponse(content="from-0-recovered"),
        ],
        name="0",
    )
    ep1 = ScriptedProvider(
        [LLMResponse(content="from-1-a"), LLMResponse(content="from-1-b")],
        name="1",
    )
    pool = EndpointPool([ep0, ep1], cooldown_seconds=9999)

    # Call 1: ep0 fails → failover to ep1
    resp1 = await pool.chat(messages=[])
    assert resp1.content == "from-1-a"

    # Call 2: ep0 is on cooldown (9999s) → goes to ep1 first
    resp2 = await pool.chat(messages=[])
    assert resp2.content == "from-1-b"
    assert ep0.calls == 1  # ep0 was NOT retried


# ---------------------------------------------------------------------------
# Cooldown expiry — endpoint recovers after cooldown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cooldown_expires_endpoint_recovers(monkeypatch):
    ep0 = ScriptedProvider(
        [
            LLMResponse(content="429 rate limit", finish_reason="error"),
            LLMResponse(content="from-0-recovered"),
        ],
        name="0",
    )
    ep1 = ScriptedProvider(
        [LLMResponse(content="from-1")],
        name="1",
    )
    pool = EndpointPool([ep0, ep1], cooldown_seconds=1)

    # Call 1: ep0 fails → failover to ep1
    resp1 = await pool.chat(messages=[])
    assert resp1.content == "from-1"

    # Simulate cooldown expiry by patching time.monotonic
    real_monotonic = time.monotonic
    monkeypatch.setattr(
        "nanobot.providers.endpoint_pool.time.monotonic",
        lambda: real_monotonic() + 2,  # 2s later, cooldown (1s) is expired
    )

    # Call 2: ep0 cooldown expired → ep0 is available again
    resp2 = await pool.chat(messages=[])
    assert resp2.content == "from-0-recovered"


# ---------------------------------------------------------------------------
# Round-robin cursor advances
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_robin_cursor():
    """After ep0 succeeds, next call starts from ep1 (round-robin)."""
    ep0 = ScriptedProvider(
        [LLMResponse(content="from-0"), LLMResponse(content="from-0-again")],
        name="0",
    )
    ep1 = ScriptedProvider(
        [LLMResponse(content="from-1"), LLMResponse(content="from-1-again")],
        name="1",
    )
    pool = EndpointPool([ep0, ep1])

    resp1 = await pool.chat(messages=[])
    assert resp1.content == "from-0"  # starts at cursor=0

    resp2 = await pool.chat(messages=[])
    assert resp2.content == "from-1"  # cursor advanced to 1

    resp3 = await pool.chat(messages=[])
    assert resp3.content == "from-0-again"  # cursor wrapped to 0


# ---------------------------------------------------------------------------
# get_default_model returns first endpoint's model
# ---------------------------------------------------------------------------


def test_get_default_model():
    ep0 = ScriptedProvider([], name="primary")
    ep1 = ScriptedProvider([], name="backup")
    pool = EndpointPool([ep0, ep1])
    assert pool.get_default_model() == "test-model-primary"


# ---------------------------------------------------------------------------
# chat_with_retry works through the pool (inherited from LLMProvider)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_with_retry_works_with_pool(monkeypatch):
    """EndpointPool inherits chat_with_retry from LLMProvider.
    Retry logic should wrap the pool's chat() which already does failover."""
    ep0 = ScriptedProvider(
        [
            # First chat_with_retry attempt: both endpoints fail
            LLMResponse(content="429 rate limit", finish_reason="error"),
            # Second chat_with_retry attempt (after retry): ep0 recovers
            LLMResponse(content="from-0-ok"),
        ],
        name="0",
    )
    ep1 = ScriptedProvider(
        [LLMResponse(content="503 server error", finish_reason="error")],
        name="1",
    )
    pool = EndpointPool([ep0, ep1], cooldown_seconds=0)  # no cooldown for simplicity

    delays: list[int] = []

    async def _fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    resp = await pool.chat_with_retry(messages=[])
    assert resp.content == "from-0-ok"
    assert len(delays) == 1  # one retry delay from chat_with_retry
