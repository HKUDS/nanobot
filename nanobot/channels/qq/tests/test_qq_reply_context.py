"""Quoted-message context for the QQ channel.

QQ's C2C/group events never send ``message_reference``: the quoted original
arrives in ``msg_elements``, linked from ``message_scene.ext`` by
``ref_msg_idx``.  The payload shapes below are copied from real traffic
captured from the QQ gateway (two C2C and two group messages, plus plain
messages as the control group).
"""

import pytest

from nanobot.channels.qq.runtime import (
    QQ_QUOTED_CONTEXT_MAX_CHARS,
    _flatten_scene_ext,
    _quoted_content_for,
    extract_quoted_content,
)

# --- Real payload shapes ----------------------------------------------------

# C2C message quoting the bot.  A plain message has no `ref_msg_idx` and no
# `msg_elements`; both appear only when the user quotes something.
C2C_QUOTING_BOT = {
    "id": "ROBOT1.0_DBiKWe9lNhRwiQwghzMwQg3fHOmxJ90S.B57.sHfcrAMcKMJhlJ4wk5MgsMmqcYidhSYdP-5IbsrfZQ6pOu0mf9OC35zpbTlRPq8A8ILhi0!",
    "content": "test reference agent",
    "message_scene": {
        "ext": [
            "ref_msg_idx=REFIDX_uBOgqP76jtuIYTCmDNJGthZK49O4ei6cIos3sHgdtfubgjFV4RVX2AD1URlzskeW",
            "msg_idx=REFIDX_+sv65NCtgisKm7eB0fzltmMfoKf14gEtdgeLHxxNuP3t1pc1n2JSZfwgAS8W12E0INOltlnT1lPyL6yrJZbYWQ",
        ],
        "source": "default",
    },
    "msg_elements": [
        {
            "content": "查完了，两处都没有叫 reference 的东西。",
            "message_type": 103,
            "msg_idx": "REFIDX_uBOgqP76jtuIYTCmDNJGthZK49O4ei6cIos3sHgdtfubgjFV4RVX2AD1URlzskeW",
        }
    ],
}

# Group message quoting the user.  Group `ext` carries an extra `auth_token`.
GROUP_QUOTING_USER = {
    "id": "ROBOT1.0_uZIDPkWlheMbQUYJKntzLfHJEMIGUOnTsFp74wy65spVBJWKV4-TxT7wTHV9biFHC82a05rtkXGkQqRfQFWGypBMNmwvGII5silxxRb-AK4NIqrVm3QhC6-bhktADRFg",
    "content": "  test reference user",
    "message_scene": {
        "ext": [
            "ref_msg_idx=REFIDX_9xpTdjgG3080nj0v1YGMwHdZWBXeRChx7OORXdh2Xc9VHvNpgceQ0PgIx6/LBhbdd3VXksZNcPQOxLTl1He34rbmIMmRJhq3rxXmKV+9mqxQvHemngO5h/ijdsYPFAbE",
            "msg_idx=REFIDX_QHGqkOiPA6mM2Zu45iSXLndZWBXeRChx7OORXdh2Xc9VHvNpgceQ0PgIx6/LBhbdd3VXksZNcPQOxLTl1He34rbmIMmRJhq3rxXmKV+9mqxQvHemngO5h/ijdsYPFAbE",
            "auth_token=N-JqY9nnTNRjjnyC6WLN7xyd7gHuhtiEfDrwWB7WF82c_5_go-2Y-l13UYmbD9yGgQUK8MVjimVtCPrhORwWsDQC4VlWMgC6B0wrSXBWHCcBwKQpHSbLbpH9Dq6n",
        ],
        "source": "default",
    },
    "msg_elements": [
        {
            "content": " test",
            "message_type": 103,
            "msg_idx": "REFIDX_9xpTdjgG3080nj0v1YGMwHdZWBXeRChx7OORXdh2Xc9VHvNpgceQ0PgIx6/LBhbdd3VXksZNcPQOxLTl1He34rbmIMmRJhq3rxXmKV+9mqxQvHemngO5h/ijdsYPFAbE",
        }
    ],
}

# Control group: a plain message.  Same key set, but no quote links.
PLAIN_MESSAGE = {
    "id": "ROBOT1.0_DBiKWe9lNhRwiQwghzMwQssT-SFcYlBDrD9xdX4A1hFupGIiqoLgkdtaAy.MKGwqGdR9Jb8mCS5DnjCudEwIjP9OC35zpbTlRPq8A8ILhi0!",
    "content": "接下来我要发几条测试消息，你忽略就行",
    "message_scene": {
        "ext": [
            "msg_idx=REFIDX_vZ+qxc1KXcODuYUzB/x9XGMfoKf14gEtdgeLHxxNuP3t1pc1n2JSZfwgAS8W12E0INOltlnT1lPyL6yrJZbYWQ",
        ],
        "source": "default",
    },
    "msg_elements": None,
}


# --- extract_quoted_content -------------------------------------------------


def test_extracts_c2c_quoted_message():
    assert extract_quoted_content(C2C_QUOTING_BOT) == "查完了，两处都没有叫 reference 的东西。"


def test_extracts_group_quoted_message():
    assert extract_quoted_content(GROUP_QUOTING_USER) == "test"


def test_plain_message_has_no_quoted_content():
    """The control group: no ref_msg_idx, so nothing to surface."""
    assert extract_quoted_content(PLAIN_MESSAGE) is None


def test_picks_element_matching_ref_idx_not_the_first():
    """Elements are matched by index, so extra elements cannot shadow the quote."""
    payload = {
        "message_scene": {"ext": ["ref_msg_idx=wanted"]},
        "msg_elements": [
            {"content": "unrelated", "msg_idx": "other"},
            {"content": "the quoted text", "msg_idx": "wanted"},
        ],
    }
    assert extract_quoted_content(payload) == "the quoted text"


def test_ref_idx_without_matching_element_returns_none():
    """Degradation: the quote is announced but the original is not attached."""
    payload = {
        "message_scene": {"ext": ["ref_msg_idx=missing"]},
        "msg_elements": [{"content": "something", "msg_idx": "other"}],
    }
    assert extract_quoted_content(payload) is None


def test_ref_idx_with_no_elements_returns_none():
    payload = {"message_scene": {"ext": ["ref_msg_idx=x"]}, "msg_elements": None}
    assert extract_quoted_content(payload) is None


def test_matched_element_without_text_returns_none():
    payload = {
        "message_scene": {"ext": ["ref_msg_idx=x"]},
        "msg_elements": [{"content": "   ", "msg_idx": "x"}],
    }
    assert extract_quoted_content(payload) is None


def test_quoted_content_is_truncated():
    payload = {
        "message_scene": {"ext": ["ref_msg_idx=x"]},
        "msg_elements": [{"content": "大" * (QQ_QUOTED_CONTEXT_MAX_CHARS + 50), "msg_idx": "x"}],
    }
    result = extract_quoted_content(payload)
    assert result is not None
    assert len(result) == QQ_QUOTED_CONTEXT_MAX_CHARS + len("...")
    assert result.endswith("...")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"message_scene": None},
        {"message_scene": {}},
        {"message_scene": {"ext": "ref_msg_idx=x"}},
        {"message_scene": {"ext": ["ref_msg_idx=x"]}, "msg_elements": "not-a-list"},
        {"message_scene": {"ext": ["ref_msg_idx=x"]}, "msg_elements": ["not-a-mapping"]},
    ],
)
def test_malformed_payloads_return_none(payload):
    """Unexpected shapes must degrade, never raise."""
    assert extract_quoted_content(payload) is None


# --- _flatten_scene_ext -----------------------------------------------------


def test_flatten_scene_ext_splits_on_first_equals_only():
    """Values (e.g. base64 indexes) may themselves contain '='."""
    assert _flatten_scene_ext({"ext": ["a=b=c", "plain", "k=v"]}) == {"a": "b=c", "k": "v"}


def test_flatten_scene_ext_ignores_non_string_entries():
    assert _flatten_scene_ext({"ext": [123, None, "k=v"]}) == {"k": "v"}


# --- _quoted_content_for ----------------------------------------------------


class _FakeMessage:
    """Duck-typed stand-in for a botpy message object."""

    def __init__(self, message_id: str, **attrs):
        self.id = message_id
        for key, value in attrs.items():
            setattr(self, key, value)


def test_quoted_content_prefers_fields_on_the_message_object(monkeypatch):
    """A botpy that parses these fields makes the payload hook redundant."""
    message = _FakeMessage(
        "whatever",
        message_scene=C2C_QUOTING_BOT["message_scene"],
        msg_elements=C2C_QUOTING_BOT["msg_elements"],
    )
    assert _quoted_content_for(message) == "查完了，两处都没有叫 reference 的东西。"


def test_quoted_content_falls_back_to_captured_payload():
    from nanobot.channels.qq import runtime

    runtime._qq_raw_payloads.clear()
    runtime._qq_raw_payloads[C2C_QUOTING_BOT["id"]] = C2C_QUOTING_BOT
    try:
        assert _quoted_content_for(_FakeMessage(C2C_QUOTING_BOT["id"])) == (
            "查完了，两处都没有叫 reference 的东西。"
        )
    finally:
        runtime._qq_raw_payloads.clear()


def test_quoted_content_is_none_for_unknown_message():
    from nanobot.channels.qq import runtime

    runtime._qq_raw_payloads.clear()
    assert _quoted_content_for(_FakeMessage("never-seen")) is None


# --- End-to-end: capture -> lookup -> content ------------------------------
#
# These exercise the real botpy message classes, so they are skipped wherever
# the optional QQ dependency is absent (same gate as the other QQ test modules).

from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

from nanobot.bus.queue import MessageBus  # noqa: E402
from nanobot.channels.qq import runtime as qq_runtime  # noqa: E402
from nanobot.channels.qq.runtime import QQChannel, QQConfig  # noqa: E402

requires_botpy = pytest.mark.skipif(
    not getattr(qq_runtime, "QQ_AVAILABLE", False),
    reason="QQ dependencies not installed (qq-botpy)",
)


def _c2c_message(data: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=data["id"],
        content=data.get("content") or "",
        author=SimpleNamespace(user_openid="user1"),
        attachments=[],
    )


def _group_message(data: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=data["id"],
        content=data.get("content") or "",
        group_openid="group123",
        author=SimpleNamespace(member_openid="user1"),
        attachments=[],
    )


@pytest.fixture
def captured():
    """Seed the payload cache the way the botpy hook does, and clean up after."""
    qq_runtime._qq_raw_payloads.clear()
    yield qq_runtime._qq_raw_payloads
    qq_runtime._qq_raw_payloads.clear()


@requires_botpy
def test_capture_hook_keeps_payload_from_real_botpy_class(captured):
    """botpy drops these fields, so the constructor hook is the only way in."""
    from botpy import message as botpy_message

    qq_runtime._install_qq_payload_capture()
    message = botpy_message.C2CMessage(api=None, event_id="ev1", data=C2C_QUOTING_BOT)

    assert captured[C2C_QUOTING_BOT["id"]] == C2C_QUOTING_BOT
    assert getattr(message, "msg_elements", None) is None, "botpy never parses these"
    assert _quoted_content_for(message) == "查完了，两处都没有叫 reference 的东西。"


@pytest.mark.asyncio
@requires_botpy
async def test_c2c_quote_is_prefixed_onto_content(captured):
    channel = QQChannel(
        QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus()
    )
    channel._handle_message = AsyncMock()
    captured[C2C_QUOTING_BOT["id"]] = C2C_QUOTING_BOT

    await channel._on_message(_c2c_message(C2C_QUOTING_BOT), is_group=False)

    content = channel._handle_message.await_args.kwargs["content"]
    assert content.startswith("[Reply to: 查完了，两处都没有叫 reference 的东西。]")
    assert content.endswith("test reference agent")


@pytest.mark.asyncio
@requires_botpy
async def test_group_quote_is_prefixed_onto_content(captured):
    channel = QQChannel(
        QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus()
    )
    channel._handle_message = AsyncMock()
    captured[GROUP_QUOTING_USER["id"]] = GROUP_QUOTING_USER

    await channel._on_message(_group_message(GROUP_QUOTING_USER), is_group=True)

    content = channel._handle_message.await_args.kwargs["content"]
    assert content.startswith("[Reply to: test]")
    assert content.endswith("test reference user")


@pytest.mark.asyncio
@requires_botpy
async def test_plain_message_content_is_unchanged(captured):
    """Control group: no quote link, so the message must reach the agent as-is."""
    channel = QQChannel(
        QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus()
    )
    channel._handle_message = AsyncMock()
    captured[PLAIN_MESSAGE["id"]] = PLAIN_MESSAGE

    await channel._on_message(_c2c_message(PLAIN_MESSAGE), is_group=False)

    assert channel._handle_message.await_args.kwargs["content"] == PLAIN_MESSAGE["content"]


@pytest.mark.asyncio
@requires_botpy
async def test_quote_without_text_is_not_dropped(captured):
    """A quote-only message carries meaning, so it must survive the empty-content gate."""
    channel = QQChannel(
        QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus()
    )
    channel._handle_message = AsyncMock()
    payload = dict(C2C_QUOTING_BOT, content="")
    captured[payload["id"]] = payload

    await channel._on_message(_c2c_message(payload), is_group=False)

    content = channel._handle_message.await_args.kwargs["content"]
    assert content == "[Reply to: 查完了，两处都没有叫 reference 的东西。]"
