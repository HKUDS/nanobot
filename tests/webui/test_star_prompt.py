from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from nanobot.webui import star_prompt


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    monkeypatch.setattr(star_prompt, "get_webui_dir", lambda: tmp_path)
    return tmp_path / "star-prompt.json"


def seed_eligible(path: Path):
    state = star_prompt.StarPromptState(
        completed_replies=10, active_days=["2026-09-20", "2026-09-21", "2026-09-22"]
    )
    path.write_text(state.model_dump_json(), encoding="utf-8")


def test_requires_completed_replies_on_three_days(state_path, monkeypatch):
    for day in range(2):
        monkeypatch.setattr(star_prompt.time, "time", lambda: 1_800_000_000 + day * 86400)
        for index in range(5):
            star_prompt.update_star_prompt("completed", turn_id=f"{day}-{index}")
    assert not star_prompt.update_star_prompt("claim")
    monkeypatch.setattr(star_prompt.time, "time", lambda: 1_800_000_000 + 2 * 86400)
    star_prompt.update_star_prompt("completed", turn_id="third-day")
    assert star_prompt.update_star_prompt("claim")
    assert not star_prompt.update_star_prompt("claim")


def test_duplicate_turns_do_not_count(state_path):
    for _ in range(15):
        star_prompt.update_star_prompt("completed", turn_id="same-turn")
    state = star_prompt.StarPromptState.model_validate_json(state_path.read_text())
    assert state.completed_replies == 1


def test_concurrent_claims_cooldown_and_limit_survive_reload(state_path, monkeypatch):
    seed_eligible(state_path)
    monkeypatch.setattr(star_prompt.time, "time", lambda: 1_800_000_000)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(lambda _: star_prompt.update_star_prompt("claim"), range(8))) == 1
    monkeypatch.setattr(star_prompt.time, "time", lambda: 1_800_000_000 + star_prompt.COOLDOWN_SECONDS - 1)
    assert not star_prompt.update_star_prompt("claim")
    monkeypatch.setattr(star_prompt.time, "time", lambda: 1_800_000_000 + star_prompt.COOLDOWN_SECONDS)
    assert star_prompt.update_star_prompt("claim")
    monkeypatch.setattr(star_prompt.time, "time", lambda: 1_900_000_000)
    assert not star_prompt.update_star_prompt("claim")


def test_dismissal_is_permanent_even_before_eligibility(state_path):
    star_prompt.update_star_prompt("dismiss")
    for index in range(20):
        star_prompt.update_star_prompt("completed", turn_id=str(index))
    assert not star_prompt.update_star_prompt("claim")
    assert star_prompt.StarPromptState.model_validate_json(state_path.read_text()).dismissed_forever


def test_corruption_and_write_failure_never_grant_display(state_path, monkeypatch):
    state_path.write_text("broken", encoding="utf-8")
    with pytest.raises(ValidationError):
        star_prompt.update_star_prompt("claim")
    seed_eligible(state_path)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(star_prompt, "_write_text_atomic", fail)
    with pytest.raises(OSError):
        star_prompt.update_star_prompt("claim")


async def test_only_successful_webui_turns_record_usage(state_path, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from nanobot.bus.queue import MessageBus
    from nanobot.bus.runtime_events import RuntimeEventContext, TurnCompleted
    from nanobot.session.manager import SessionManager
    from nanobot.session.webui_turns import WebuiTurnCoordinator
    from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY

    bus = MessageBus()
    coordinator = WebuiTurnCoordinator(bus, SessionManager(tmp_path), Mock())
    monkeypatch.setattr(coordinator, "handle_turn_end", AsyncMock())
    monkeypatch.setattr(coordinator, "_schedule_title_update_from_event", Mock())
    with coordinator.connected():
        for channel, outcome in [("websocket", "completed"), ("websocket", "failed"),
                                 ("websocket", "cancelled"), ("telegram", "completed")]:
            await bus.publish(TurnCompleted(
                context=RuntimeEventContext(
                    channel=channel, chat_id="test", session_key=f"{channel}:test",
                    metadata={WEBUI_TURN_METADATA_KEY: f"{channel}-{outcome}"},
                ),
                outcome=outcome,
            ))
    state = star_prompt.StarPromptState.model_validate_json(state_path.read_text())
    assert state.completed_replies == 1
