from nanobot.bus.events import InboundMessage
from nanobot.session.routing import routing_context_for_message


def test_routing_context_keeps_telegram_topic_without_stale_message_id() -> None:
    context = routing_context_for_message(
        InboundMessage(
            channel="telegram",
            sender_id="user-1",
            chat_id="-100123",
            content="set a reminder",
            metadata={
                "message_id": 100,
                "message_thread_id": 42,
                "_progress": True,
            },
            session_key_override="telegram:-100123:topic:42",
        )
    )

    assert context == {
        "channel": "telegram",
        "chat_id": "-100123",
        "metadata": {"message_thread_id": 42},
    }


def test_routing_context_keeps_feishu_topic_anchor() -> None:
    context = routing_context_for_message(
        InboundMessage(
            channel="feishu",
            sender_id="ou_user",
            chat_id="oc_chat",
            content="set a reminder",
            metadata={
                "chat_type": "group",
                "message_id": "om_msg",
                "thread_id": "omt_thread",
                "_progress": True,
            },
            session_key_override="feishu:oc_chat:om_root",
        )
    )

    assert context == {
        "channel": "feishu",
        "chat_id": "oc_chat",
        "metadata": {
            "chat_type": "group",
            "message_id": "om_msg",
            "thread_id": "omt_thread",
        },
    }
