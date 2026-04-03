from abc import ABC
import pytest
from nanobot.session.base import BaseSessionManager


def test_base_session_manager_is_abstract():
    assert issubclass(BaseSessionManager, ABC)


def test_cannot_instantiate_base():
    with pytest.raises(TypeError):
        BaseSessionManager()  # type: ignore


def test_concrete_subclass_must_implement_all_methods():
    class Incomplete(BaseSessionManager):
        pass  # 未实现任何方法

    with pytest.raises(TypeError):
        Incomplete()


def test_concrete_subclass_can_instantiate():
    from nanobot.session.manager import Session

    class MinimalManager(BaseSessionManager):
        def get_or_create(self, key: str) -> Session:
            return Session(key=key)

        def save(self, session: Session) -> None:
            pass

        def invalidate(self, key: str) -> None:
            pass

        def list_sessions(self):
            return []

    mgr = MinimalManager()
    s = mgr.get_or_create("test:1")
    assert s.key == "test:1"
