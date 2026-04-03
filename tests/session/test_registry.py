import pytest
from nanobot.session.registry import discover_session_manager


def test_discover_normal_returns_normal_session_manager(tmp_path):
    from nanobot.session.manager import NormalSessionManager
    cls = discover_session_manager("normal")
    assert cls is NormalSessionManager


def test_discover_unknown_raises_value_error():
    with pytest.raises(ValueError, match="Unknown session backend: 'nonexistent'"):
        discover_session_manager("nonexistent")


def test_discovered_class_is_instantiable(tmp_path):
    cls = discover_session_manager("normal")
    mgr = cls(tmp_path)
    session = mgr.get_or_create("chan:123")
    assert session.key == "chan:123"
