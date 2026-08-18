from pathlib import Path

import pytest

from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import (
    SessionHandleResolver,
    normalize_session_handle,
    session_handle_for_key,
)


def _persist(manager: SessionManager, key: str) -> None:
    manager.save(manager.get_or_create(key))


def test_handle_is_stable_and_contains_no_session_key() -> None:
    first = session_handle_for_key("websocket:review")
    second = session_handle_for_key("websocket:review")

    assert first == second
    assert first.id.startswith("handle_")
    assert first.name.count("-") == 1
    assert "websocket" not in str(first.public_payload())
    assert first.public_payload() == {"id": first.id, "name": first.name}


def test_different_session_keys_have_different_handles() -> None:
    first = session_handle_for_key("websocket:first")
    second = session_handle_for_key("telegram:second")

    assert first.id != second.id
    assert first.name != second.name


def test_resolver_lists_every_persisted_channel_and_resolves_by_name(
    tmp_path: Path,
) -> None:
    manager = SessionManager(tmp_path)
    _persist(manager, "websocket:first")
    _persist(manager, "telegram:second")
    resolver = SessionHandleResolver(manager)

    handles = resolver.list_all()

    assert {handle.session_key for handle in handles} == {
        "websocket:first",
        "telegram:second",
    }
    for handle in handles:
        assert resolver.resolve(f"@{handle.name}") == handle
    assert resolver.resolve("@missing-0000000000") is None


def test_normalize_session_handle_accepts_optional_at_prefix() -> None:
    handle = session_handle_for_key("slack:channel")

    assert normalize_session_handle(handle.name.upper()) == handle.name
    assert normalize_session_handle(f"@{handle.name}") == handle.name
    with pytest.raises(ValueError, match="invalid"):
        normalize_session_handle("not a handle")
