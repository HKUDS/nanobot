from nanobot.webui.transcript import TranscriptReplayStats


def test_grouped_backfill_keeps_response_input_order_in_page_and_index(history, tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:backfill-order"
    ids = ["input:first", "input:second", "input:third"]
    messages = [
        {"role": "user", "content": name, "input_id": input_id}
        for name, input_id in zip(("first", "second", "third"), ids)
    ] + [{"role": "assistant", "content": "answer"}]
    history.append(key, {"event": "user", "text": "second", "input_id": ids[1]})
    history.append(key, {"event": "message", "text": "answer", "response_input_ids": ids})
    history.append(key, {"event": "turn_end"})
    def loader():
        return messages
    index = history.prompts(key, session_messages_loader=loader)
    stats = TranscriptReplayStats()
    page = history.build(key, limit=1, session_messages_loader=loader, stats=stats)
    users = [event for event in page["events"] if event["event"] == "user_message"]
    assert [event["text"] for event in users] == ["first", "second", "third"]
    assert [prompt["inputId"] for prompt in index] == ids
    assert [prompt["id"] for prompt in index] == [event["projection_id"] for event in users]
    assert stats.parsed_records < 10


def test_identity_backfill_is_not_repeated_by_legacy_answer_matching(history, tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:backfill-duplicate"
    messages = [
        {"role": "user", "content": "question", "input_id": "input:one"},
        {"role": "assistant", "content": "answer"},
    ]
    history.append(key, {"event": "message", "text": "answer"})
    history.append(key, {"event": "turn_end"})
    history.append(key, {"event": "message", "text": "answer", "response_input_ids": ["input:one"]})
    history.append(key, {"event": "turn_end"})
    def loader():
        return messages
    index = history.prompts(key, session_messages_loader=loader)
    page = history.build(key, limit=10, session_messages_loader=loader)
    users = [event for event in page["events"] if event["event"] == "user_message"]
    assert [prompt["inputId"] for prompt in index] == ["input:one"]
    assert [event["text"] for event in users] == ["question"]
    assert index[0]["id"] == users[0]["projection_id"]
    latest = history.build(key, limit=1, session_messages_loader=loader)
    older = history.build(key, limit=1, before=latest["page"]["before_cursor"], session_messages_loader=loader)
    paged_users = [event for part in (older, latest) for event in part["events"] if event["event"] == "user_message"]
    assert [event["projection_id"] for event in paged_users] == [index[0]["id"]]


def test_empty_response_inputs_do_not_use_legacy_answer_matching(history, tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:empty-response-inputs"
    messages = [
        {"role": "user", "content": "question", "input_id": "input:one"},
        {"role": "assistant", "content": "answer"},
    ]
    history.append(key, {"event": "message", "text": "answer", "response_input_ids": []})
    history.append(key, {"event": "turn_end"})
    history.append(key, {"event": "message", "text": "answer"})
    history.append(key, {"event": "turn_end"})

    def loader():
        return messages

    index = history.prompts(key, session_messages_loader=loader)
    page = history.build(key, limit=10, session_messages_loader=loader)
    users = [event for event in page["events"] if event["event"] == "user_message"]
    assert [prompt["inputId"] for prompt in index] == ["input:one"]
    assert [event["projection_id"] for event in users] == [index[0]["id"]]
    latest = history.build(key, limit=1, session_messages_loader=loader)
    older = history.build(key, limit=1, before=latest["page"]["before_cursor"], session_messages_loader=loader)
    assert not [event for event in older["events"] if event["event"] == "user_message"]
    assert [event["projection_id"] for event in latest["events"] if event["event"] == "user_message"] == [index[0]["id"]]


def test_truncated_turn_applies_plan_when_reference_anchor_is_dropped(history, tmp_path, monkeypatch):
    from nanobot.webui import transcript
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 5)
    key = "websocket:truncated-backfill"
    ids = ["input:a", "input:b", "input:c"]
    messages = [{"role": "user", "content": text, "input_id": ident}
                for text, ident in zip(("A", "B", "C"), ids)]
    history.append(key, {"event": "user", "text": "B", "input_id": ids[1]})
    history.append(key, {"event": "message", "text": "first", "response_input_ids": ids[:2]})
    for i in range(12):
        history.append(key, {"event": "message", "kind": "tool_hint", "text": str(i)})
    history.append(key, {"event": "message", "text": "last", "response_input_ids": ids[2:]})
    history.append(key, {"event": "turn_end"})
    index = history.prompts(key, session_messages_loader=lambda: messages)
    page = history.build(key, limit=10, session_messages_loader=lambda: messages)
    users = [event for event in page["events"] if event["event"] == "user_message"]
    assert page["page"]["truncated_oversized_turn"]
    assert not page["page"]["has_more_before"]
    assert [event["text"] for event in users] == ["A", "B", "C"]
    assert [event["projection_id"] for event in users] == [prompt["id"] for prompt in index]


def test_truncated_turn_recovers_even_if_all_missing_references_were_dropped(history, tmp_path, monkeypatch):
    from nanobot.webui import transcript
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 4)
    key = "websocket:truncated-no-reference"
    messages = [{"role": "user", "content": "A", "input_id": "a"}]
    history.append(key, {"event": "user", "text": "B", "input_id": "b"})
    history.append(key, {"event": "message", "text": "old", "response_input_ids": ["a", "b"]})
    for i in range(10):
        history.append(key, {"event": "message", "kind": "tool_hint", "text": str(i)})
    history.append(key, {"event": "message", "text": "new"})
    history.append(key, {"event": "turn_end"})
    index = history.prompts(key, session_messages_loader=lambda: messages)
    page = history.build(key, limit=10, session_messages_loader=lambda: messages)
    users = [event for event in page["events"] if event["event"] == "user_message"]
    assert page["page"]["truncated_oversized_turn"]
    assert [event["text"] for event in users] == ["A", "B"]
    assert [event["projection_id"] for event in users] == [prompt["id"] for prompt in index]


def test_completed_stream_compaction_and_truncation_keep_shared_backfill_anchor(history, tmp_path, monkeypatch):
    from nanobot.webui import transcript

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:stream-anchor"
    ids = ["input:a", "input:b", "input:c"]
    messages = [{"role": "user", "content": text, "input_id": ident}
                for text, ident in zip(("A", "B", "C"), ids)]
    history.append(key, {"event": "user", "text": "B", "input_id": ids[1]})
    history.append(key, {"event": "message", "text": "answer", "response_input_ids": ids})
    for i in range(10):
        history.append(key, {"event": "message", "kind": "tool_hint", "text": str(i)})
    for text in ("one", "two", "three"):
        history.append(key, {"event": "delta", "text": text})
    history.append(key, {"event": "stream_end", "text": "onetwothree"})
    history.append(key, {"event": "turn_end"})

    def loader():
        return messages
    index = history.prompts(key, session_messages_loader=loader)
    stats = TranscriptReplayStats()
    full = history.build(key, limit=10, session_messages_loader=loader, stats=stats)
    assert stats.compacted_delta_records == 3
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 8)
    truncated_stats = TranscriptReplayStats()
    truncated = history.build(key, limit=10, session_messages_loader=loader, stats=truncated_stats)
    assert truncated["page"]["truncated_oversized_turn"]
    assert truncated_stats.compacted_delta_records == 3
    expected_ids = [prompt["id"] for prompt in index]
    assert [prompt["inputId"] for prompt in index] == ids
    for page in (full, truncated):
        users = [event for event in page["events"] if event["event"] == "user_message"]
        assert [event["text"] for event in users] == ["A", "B", "C"]
        assert [event["projection_id"] for event in users] == expected_ids
