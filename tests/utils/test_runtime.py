from nanobot.utils.runtime import build_length_recovery_message


def test_length_recovery_message_anchors_the_existing_tail() -> None:
    omitted_prefix = "OMITTED_PREFIX"
    tail = "x" * 500

    message = build_length_recovery_message(omitted_prefix + tail)

    assert message["role"] == "user"
    assert omitted_prefix not in message["content"]
    assert f"<already_delivered_tail>\n{tail}\n</already_delivered_tail>" in message["content"]
    assert "Output only new continuation text" in message["content"]
    assert "Break remaining work into smaller steps" not in message["content"]
