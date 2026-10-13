from unittest.mock import MagicMock

import pytest

from nanobot.providers.base import LLMUsage
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY
from nanobot.session.recovery import RECOVERY_METADATA_KEY
from nanobot.webui.session_projection import WebUISessionProjection


def test_attach_fields_restore_session_runtime_metadata() -> None:
    usage = LLMUsage.reported(input_tokens=120, output_tokens=8, total_tokens=175)
    sessions = MagicMock()
    sessions.read_session_metadata.return_value = {
        "metadata": {
            SESSION_MODEL_PRESET_METADATA_KEY: "Deep Research",
            RECOVERY_METADATA_KEY: {
                "status": "recovered",
                "recovery_id": "recovery-1",
                "reason": "answer_restored",
            },
            "_last_usage": usage.to_dict(),
        }
    }

    projection = WebUISessionProjection(sessions)

    assert projection.attach_fields("websocket:chat-1") == {
        "model_preset": "Deep Research",
        "recovery_state": {
            "status": "recovered",
            "recovery_id": "recovery-1",
            "reason": "answer_restored",
        },
        "usage": usage.to_turn_dict(),
    }
    sessions.read_session_metadata.assert_called_once_with("websocket:chat-1")


def test_attach_fields_tolerate_missing_or_invalid_session_metadata() -> None:
    sessions = MagicMock()
    sessions.read_session_metadata.return_value = {
        "metadata": {SESSION_MODEL_PRESET_METADATA_KEY: 42}
    }
    log = MagicMock()
    projection = WebUISessionProjection(sessions, log=log)

    assert projection.attach_fields("websocket:invalid") == {"model_preset": None}
    log.warning.assert_called_once()
    assert WebUISessionProjection(None).attach_fields("websocket:missing") == {}


def test_hydration_events_restore_goal_and_running_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = MagicMock()
    sessions.read_session_metadata.return_value = {
        "metadata": {
            "goal_state": {
                "status": "active",
                "objective": "finish boundary split",
                "ui_summary": "Refactoring",
            }
        }
    }
    monkeypatch.setattr(
        "nanobot.webui.session_projection.websocket_turn_wall_started_at",
        lambda _chat_id: 42.5,
    )
    monkeypatch.setattr(
        "nanobot.webui.session_projection.websocket_turn_id",
        lambda _chat_id: "turn-1",
    )

    events = WebUISessionProjection(sessions).hydration_events(
        "websocket:chat-1",
        "chat-1",
    )

    assert events == (
        {
            "event": "goal_state",
            "chat_id": "chat-1",
            "goal_state": {
                "active": True,
                "status": "active",
                "ui_summary": "Refactoring",
                "objective": "finish boundary split",
            },
        },
        {
            "event": "goal_status",
            "chat_id": "chat-1",
            "status": "running",
            "started_at": 42.5,
            "turn_id": "turn-1",
        },
    )


def test_hydration_events_are_quiet_without_actionable_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = MagicMock()
    sessions.read_session_metadata.return_value = {"metadata": {}}
    monkeypatch.setattr(
        "nanobot.webui.session_projection.websocket_turn_wall_started_at",
        lambda _chat_id: None,
    )

    assert WebUISessionProjection(sessions).hydration_events(
        "websocket:chat-1",
        "chat-1",
    ) == ()
