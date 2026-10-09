"""Private continuation state stays outside public conversation history."""

import json
from pathlib import Path

from nanobot.providers.base import ProviderConversationState
from nanobot.session.manager import Session, SessionManager


def test_provider_state_round_trips_in_private_record_only(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    secret = "encrypted-reasoning-blob"
    session = Session(
        key="test:provider-state",
        provider_state=ProviderConversationState(
            kind="openai_responses",
            provider="openai:https://api.openai.com/v1",
            model="gpt-5.6",
            version=1,
            payload={
                "items": [
                    {
                        "type": "reasoning",
                        "encrypted_content": secret,
                    }
                ]
            },
            pending_messages=[{"role": "user", "content": "continue"}],
        ),
    )
    session.add_message("user", "hello")
    mgr.save(session)

    mgr.invalidate(session.key)
    loaded = mgr.get_or_create(session.key)
    assert loaded.provider_state is not None
    assert loaded.provider_state.to_private_record() == session.provider_state.to_private_record()

    public_payload = mgr.read_session_file(session.key)
    assert public_payload is not None
    assert public_payload["messages"] == [session.messages[0]]
    assert secret not in json.dumps(public_payload)
    assert secret not in json.dumps(mgr.list_sessions())

def test_provider_state_does_not_consume_list_preview_budget(
    tmp_path: Path,
    monkeypatch,
):
    mgr = SessionManager(tmp_path)
    session = Session(
        key="test:provider-state-preview",
        provider_state=ProviderConversationState(
            kind="openai_responses",
            provider="openai:test",
            model="test-model",
            version=1,
            payload={"items": [{"encrypted_content": "x" * 200}]},
        ),
    )
    session.add_message("user", "visible preview")
    mgr.save(session)

    assert mgr.list_sessions()[0]["preview"] == "visible preview"

def test_clear_and_fork_discard_provider_state(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": []},
    )
    source = Session(key="test:state-source", provider_state=state)
    source.add_message("user", "hello")
    mgr.save(source)

    fork = mgr.fork_session_before_user_index(
        source.key,
        "test:state-fork",
        1,
    )
    assert fork is not None
    assert fork.provider_state is None

    source.clear()
    assert source.provider_state is None
