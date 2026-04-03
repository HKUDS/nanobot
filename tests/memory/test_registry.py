import pytest
from nanobot.memory.registry import discover_memory_store


def test_discover_normal_returns_normal_memory_store():
    from nanobot.memory.store import NormalMemoryStore
    cls = discover_memory_store("normal")
    assert cls is NormalMemoryStore


def test_discover_unknown_raises_value_error():
    with pytest.raises(ValueError, match="Unknown memory backend: 'nonexistent'"):
        discover_memory_store("nonexistent")


def test_discovered_class_is_instantiable(tmp_path):
    cls = discover_memory_store("normal")
    store = cls(tmp_path)
    assert store.read_long_term() == ""
