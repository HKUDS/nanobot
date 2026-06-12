import pytest

from nanobot.cron.session_delivery import bound_session_inbound_context


@pytest.mark.parametrize(
    ("session_key", "expected"),
    [
        ("websocket:chat-1", ("websocket", "chat-1", {})),
        (
            "discord:456:thread:777",
            (
                "discord",
                "777",
                {
                    "context_chat_id": "456",
                    "parent_channel_id": "456",
                    "thread_id": "777",
                },
            ),
        ),
        (
            "feishu:oc_abc:om_root123",
            (
                "feishu",
                "oc_abc",
                {
                    "chat_type": "group",
                    "message_id": "om_root123",
                    "thread_id": "om_root123",
                },
            ),
        ),
        ("slack:C123:1700.42", ("slack", "C123", {"slack": {"thread_ts": "1700.42"}})),
        ("telegram:-100123:topic:42", ("telegram", "-100123", {"message_thread_id": 42})),
        ("dingtalk:group:conv-1:user-1", ("dingtalk", "group:conv-1", {})),
    ],
)
def test_bound_session_inbound_context(session_key, expected) -> None:
    assert bound_session_inbound_context(session_key) == expected


def test_bound_session_inbound_context_rejects_invalid_key() -> None:
    with pytest.raises(ValueError):
        bound_session_inbound_context("unified")
