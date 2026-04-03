from abc import ABC
import pytest
from nanobot.memory.base import BaseMemoryStore


def test_base_memory_store_is_abstract():
    assert issubclass(BaseMemoryStore, ABC)


def test_cannot_instantiate_base():
    with pytest.raises(TypeError):
        BaseMemoryStore()  # type: ignore


def test_get_memory_context_default_impl():
    """get_memory_context has a default implementation using read_long_term."""

    class MinimalStore(BaseMemoryStore):
        def read_long_term(self) -> str:
            return "fact: sky is blue"

        def write_long_term(self, content: str) -> None:
            pass

        def append_history(self, entry: str) -> None:
            pass

    store = MinimalStore()
    ctx = store.get_memory_context()
    assert "fact: sky is blue" in ctx


def test_get_memory_context_empty_returns_empty_string():
    class EmptyStore(BaseMemoryStore):
        def read_long_term(self) -> str:
            return ""

        def write_long_term(self, content: str) -> None:
            pass

        def append_history(self, entry: str) -> None:
            pass

    assert EmptyStore().get_memory_context() == ""
