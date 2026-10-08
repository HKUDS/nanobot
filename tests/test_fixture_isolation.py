import time
from pathlib import Path

import pytest

from nanobot.llm_usage import LLMCallRecord, get_llm_usage_store
from nanobot.session.manager import SessionManager
from nanobot.webui import star_prompt


@pytest.mark.parametrize("_iteration", range(2))
def test_runtime_stores_are_isolated_between_parameter_cases(
    tmp_path: Path, _iteration: int,
) -> None:
    sessions = SessionManager(tmp_path.parent / "shared-workspace")
    session = sessions.get_or_create("websocket:fixture-isolation")
    assert session.messages == []
    session.add_message("user", "isolated message")
    sessions.save(session)

    usage = get_llm_usage_store(tmp_path / "usage.sqlite3")
    assert usage.recent_calls() == []
    usage.record(LLMCallRecord(
        started_at_ms=int(time.time() * 1000), duration_ms=1, provider="test", model="test",
        source="user", stream=False, finish_reason="stop",
    ))
    assert len(usage.recent_calls()) == 1

    state_path = star_prompt.get_webui_dir() / "star-prompt.json"
    assert not state_path.exists()
    star_prompt.update_star_prompt("completed", turn_id="fixture-isolation")
    assert state_path.exists()
