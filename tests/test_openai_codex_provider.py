from nanobot.providers.openai_codex_provider import MAX_TOOL_CALL_ID_LEN, _compose_tool_call_id


def test_compose_tool_call_id_keeps_composite_when_within_limit() -> None:
    value = _compose_tool_call_id("call_123", "fc_456")

    assert value == "call_123|fc_456"
    assert len(value) <= MAX_TOOL_CALL_ID_LEN


def test_compose_tool_call_id_falls_back_to_call_id_when_composite_is_too_long() -> None:
    call_id = "call_" + ("x" * 40)
    item_id = "fc_" + ("y" * 40)

    value = _compose_tool_call_id(call_id, item_id)

    assert value == call_id
    assert len(value) <= MAX_TOOL_CALL_ID_LEN


def test_compose_tool_call_id_hashes_when_call_id_also_too_long() -> None:
    call_id = "call_" + ("x" * 90)
    item_id = "fc_" + ("y" * 40)

    value = _compose_tool_call_id(call_id, item_id)
    value_again = _compose_tool_call_id(call_id, item_id)

    assert len(value) <= MAX_TOOL_CALL_ID_LEN
    assert value == value_again
    assert value != call_id
