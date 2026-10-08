from pathlib import Path

import pytest

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

    state_path = star_prompt.get_webui_dir() / "star-prompt.json"
    assert not state_path.exists()
    star_prompt.update_star_prompt("completed", turn_id="fixture-isolation")
    assert state_path.exists()
