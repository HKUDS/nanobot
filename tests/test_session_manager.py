from pathlib import Path

import pytest

from nanobot.session.manager import Session, SessionManager


def test_rename_session_moves_file_and_updates_metadata(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = Session(key="web:alpha")
    session.add_message("user", "hello")
    manager.save(session)

    renamed = manager.rename_session("web:alpha", "web:beta")

    assert renamed.key == "web:beta"
    assert not manager._get_session_path("web:alpha").exists()
    assert manager._get_session_path("web:beta").exists()

    reloaded = manager.get_or_create("web:beta")
    assert reloaded.key == "web:beta"
    assert reloaded.messages[0]["content"] == "hello"


def test_rename_session_rejects_existing_target(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    manager.save(Session(key="web:alpha"))
    manager.save(Session(key="web:beta"))

    with pytest.raises(FileExistsError):
        manager.rename_session("web:alpha", "web:beta")


def test_session_metadata_round_trips(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = Session(
        key="web:pgx",
        metadata={"template_id": "pharmacogenomics", "template": {"name": "Pharmacogenomics Analyst"}},
    )
    manager.save(session)
    manager.invalidate("web:pgx")

    reloaded = manager.get_or_create("web:pgx")

    assert reloaded.metadata["template_id"] == "pharmacogenomics"
    assert reloaded.metadata["template"]["name"] == "Pharmacogenomics Analyst"
