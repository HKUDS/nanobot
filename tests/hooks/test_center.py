"""Tests for HookCenter registry and dispatch engine."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from nanobot.hooks.center import HookCenter
from nanobot.hooks.event_types import (
    BeforeIteration,
    FinalizeContent,
    OnStream,
    OnStreamEnd,
)
from nanobot.hooks.protocols import Deny, HookResult, Modified

# ---------------------------------------------------------------------------
# Happy path: register_internal handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_internal_handler_is_called():
    center = HookCenter()
    session = center.create_session()
    handler = Mock(return_value=None)
    center.register_internal(session, BeforeIteration, handler)
    event = BeforeIteration(iteration=0, messages=[])

    await center.emit(event, session)

    handler.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_register_internal_handler_sets_mode():
    center = HookCenter()
    session = center.create_session()
    handler = Mock(return_value=None)

    center.register_internal(session, BeforeIteration, handler, mode="guard")
    event = BeforeIteration(iteration=0, messages=[])
    await center.emit(event, session)

    handler.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# Happy path: register external handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_external_handler_is_called():
    center = HookCenter()
    session = center.create_session()
    handler = Mock(return_value=None)
    center.register(BeforeIteration, handler, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])

    await center.emit(event, session)

    handler.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_guard_handler_returns_deny_stops_emit():
    center = HookCenter()
    session = center.create_session()
    guard = Mock(return_value=Deny(reason="blocked"))
    later = Mock()

    center.register(BeforeIteration, guard, mode="guard")
    center.register(BeforeIteration, later, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])

    result = await center.emit(event, session)

    assert isinstance(result, Deny)
    assert result.reason == "blocked"
    guard.assert_called_once_with(event)
    later.assert_not_called()


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transform_pipeline_second_sees_first_result():
    center = HookCenter()
    session = center.create_session()
    events_seen: list[int] = []

    async def t1(ev: BeforeIteration) -> HookResult:
        events_seen.append(ev.iteration)
        ev.iteration = 99
        return Modified(data={"iteration": 99})

    async def t2(ev: BeforeIteration) -> HookResult:
        events_seen.append(ev.iteration)
        return None

    center.register(BeforeIteration, t1, mode="transform")
    center.register(BeforeIteration, t2, mode="transform")
    event = BeforeIteration(iteration=0, messages=[])

    await center.emit(event, session)

    assert events_seen == [0, 99]


# ---------------------------------------------------------------------------
# Observe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observe_handler_called_return_none_ignored():
    center = HookCenter()
    session = center.create_session()
    handler = Mock(return_value=None)

    center.register(BeforeIteration, handler, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])
    result = await center.emit(event, session)

    handler.assert_called_once_with(event)
    assert result is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_with_no_handlers_is_noop():
    center = HookCenter()
    session = center.create_session()
    event = BeforeIteration(iteration=0, messages=[])

    result = await center.emit(event, session)

    assert result is None


@pytest.mark.asyncio
async def test_guard_deny_blocks_transforms_and_observes():
    center = HookCenter()
    session = center.create_session()
    guard = Mock(return_value=Deny("stop"))
    tx = Mock()
    obs = Mock()

    center.register(BeforeIteration, guard, mode="guard")
    center.register(BeforeIteration, tx, mode="transform")
    center.register(BeforeIteration, obs, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])

    result = await center.emit(event, session)

    assert isinstance(result, Deny)
    tx.assert_not_called()
    obs.assert_not_called()


# ---------------------------------------------------------------------------
# Dedup: same handler + event type + mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_handler_registered_twice_dedup():
    center = HookCenter()
    session = center.create_session()
    handler = Mock(return_value=None)

    center.register(BeforeIteration, handler, mode="guard")
    center.register(BeforeIteration, handler, mode="guard")
    event = BeforeIteration(iteration=0, messages=[])

    await center.emit(event, session)

    handler.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_same_handler_different_modes_not_deduped():
    center = HookCenter()
    session = center.create_session()
    handler = Mock(return_value=None)

    center.register(BeforeIteration, handler, mode="guard")
    center.register(BeforeIteration, handler, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])

    await center.emit(event, session)

    assert handler.call_count == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_error_reraise_false_caught():
    center = HookCenter()
    session = center.create_session()

    async def bad_handler(event):
        raise RuntimeError("boom")

    good = Mock(return_value=None)

    center.register(BeforeIteration, bad_handler, mode="observe")
    center.register(BeforeIteration, good, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])

    result = await center.emit(event, session)

    assert result is None
    good.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_handler_error_reraise_true_propagates():
    center = HookCenter()
    session = center.create_session()

    async def bad_handler(event):
        raise RuntimeError("propagate-me")

    center.register_internal(session, BeforeIteration, bad_handler, reraise=True, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])

    with pytest.raises(RuntimeError, match="propagate-me"):
        await center.emit(event, session)


@pytest.mark.asyncio
async def test_internal_handler_reraise_false_caught_others_continue():
    center = HookCenter()
    session = center.create_session()

    async def bad(event):
        raise RuntimeError("err")

    good = Mock(return_value=None)

    center.register_internal(session, BeforeIteration, bad, reraise=False, mode="observe")
    center.register_internal(session, BeforeIteration, good, reraise=False, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])

    await center.emit(event, session)

    good.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# wants_streaming
# ---------------------------------------------------------------------------


def test_wants_streaming_false_with_no_handlers():
    center = HookCenter()
    session = center.create_session()

    assert center.wants_streaming(session) is False


def test_wants_streaming_true_when_internal_streaming_handler_registered():
    center = HookCenter()
    session = center.create_session()

    center.register_internal(session, OnStream, Mock(), mode="observe")

    assert center.wants_streaming(session) is True


def test_wants_streaming_true_when_external_streaming_handler_registered():
    center = HookCenter()

    center.register(OnStream, Mock(), mode="observe")

    session = center.create_session()
    assert center.wants_streaming(session) is True


def test_wants_streaming_true_for_on_stream_end():
    center = HookCenter()

    center.register(OnStreamEnd, Mock(), mode="observe")

    session = center.create_session()
    assert center.wants_streaming(session) is True


# ---------------------------------------------------------------------------
# finalize_content
# ---------------------------------------------------------------------------


def test_finalize_content_pipeline():
    center = HookCenter()
    session = center.create_session()

    def upper(c: str | None) -> str | None:
        return c.upper() if c else c

    def suffix(c: str | None) -> str | None:
        return (c + "!") if c else c

    center.register_internal(session, FinalizeContent, upper, mode="transform")
    center.register_internal(session, FinalizeContent, suffix, mode="transform")

    result = center.finalize_content("hello", session)
    assert result == "HELLO!"


def test_finalize_content_none_passthrough():
    center = HookCenter()
    session = center.create_session()

    result = center.finalize_content(None, session)
    assert result is None


def test_finalize_content_external_handlers():
    center = HookCenter()
    session = center.create_session()

    def internal(c):
        return c.upper() if c else c

    def external(c):
        return (c + "!") if c else c

    center.register_internal(session, FinalizeContent, internal, mode="transform")
    center.register(FinalizeContent, external, mode="transform")

    result = center.finalize_content("hey", session)

    assert result == "HEY!"


def test_finalize_content_error_caught():
    center = HookCenter()
    session = center.create_session()

    def bad(c):
        raise RuntimeError("boom")

    def good(c):
        return (c or "") + "suffix"

    center.register_internal(session, FinalizeContent, bad, reraise=False, mode="transform")
    center.register_internal(session, FinalizeContent, good, mode="transform")

    result = center.finalize_content("hi", session)
    assert result == "hisuffix"


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_clears_all_handlers():
    center = HookCenter()
    session = center.create_session()
    handler = Mock(return_value=None)

    center.register(BeforeIteration, handler, mode="observe")
    center.reset()

    event = BeforeIteration(iteration=0, messages=[])
    await center.emit(event, session)

    handler.assert_not_called()


# ---------------------------------------------------------------------------
# Internal vs external independence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_does_not_overwrite_internal():
    center = HookCenter()
    session = center.create_session()

    internal = Mock(return_value=None)
    external = Mock(return_value=None)

    center.register_internal(session, BeforeIteration, internal, mode="observe")
    center.register(BeforeIteration, external, mode="observe")

    event = BeforeIteration(iteration=0, messages=[])
    await center.emit(event, session)

    internal.assert_called_once_with(event)
    external.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# Guard → Transform → Observe order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_order_guard_transform_observe():
    center = HookCenter()
    session = center.create_session()
    order: list[str] = []

    async def g(event):
        order.append("guard")
        return None

    async def t(event):
        order.append("transform")
        return None

    async def o(event):
        order.append("observe")
        return None

    center.register(BeforeIteration, g, mode="guard")
    center.register(BeforeIteration, t, mode="transform")
    center.register(BeforeIteration, o, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])

    await center.emit(event, session)

    assert order == ["guard", "transform", "observe"]


# ---------------------------------------------------------------------------
# Internal before external order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_runs_before_external():
    center = HookCenter()
    session = center.create_session()
    order: list[str] = []

    async def internal_obs(event):
        order.append("internal")
        return None

    async def external_obs(event):
        order.append("external")
        return None

    center.register_internal(session, BeforeIteration, internal_obs, mode="observe")
    center.register(BeforeIteration, external_obs, mode="observe")
    event = BeforeIteration(iteration=0, messages=[])

    await center.emit(event, session)

    assert order == ["internal", "external"]


# ---------------------------------------------------------------------------
# register_point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Invalid mode
# ---------------------------------------------------------------------------


def test_register_invalid_mode_raises():
    center = HookCenter()
    with pytest.raises(ValueError, match="Unknown mode"):
        center.register(BeforeIteration, Mock(), mode="invalid")


def test_register_internal_invalid_mode_raises():
    center = HookCenter()
    session = center.create_session()
    with pytest.raises(ValueError, match="Unknown mode"):
        center.register_internal(session, BeforeIteration, Mock(), mode="nope")


# ---------------------------------------------------------------------------
# discover placeholder
# ---------------------------------------------------------------------------


def test_discover_is_noop_placeholder():
    center = HookCenter()
    center.discover(None)
