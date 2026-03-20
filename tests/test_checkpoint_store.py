"""Tests for CheckpointStore and CheckpointState."""

import json
from pathlib import Path

from nanobot.agent.checkpoint import CheckpointState, CheckpointStore


def _make_state(task_id: str = "abc12345", iteration: int = 3) -> CheckpointState:
    """Create a sample checkpoint state."""
    return CheckpointState(
        task_id=task_id,
        iteration=iteration,
        messages=[
            {"role": "system", "content": "You are a subagent."},
            {"role": "user", "content": "Search for Python docs."},
            {"role": "assistant", "content": "I'll search.", "tool_calls": []},
            {"role": "tool", "tool_call_id": "c1", "name": "web_search", "content": "results..."},
        ],
        task="Search for Python documentation",
        label="Python docs search",
        origin={"channel": "telegram", "chat_id": "12345"},
        completed_tools=["web_search", "web_fetch", "write_file"],
    )


class TestCheckpointState:
    """Test the CheckpointState dataclass."""

    def test_to_dict_roundtrip(self) -> None:
        state = _make_state()
        data = state.to_dict()
        restored = CheckpointState.from_dict(data)

        assert restored.task_id == state.task_id
        assert restored.iteration == state.iteration
        assert restored.messages == state.messages
        assert restored.task == state.task
        assert restored.label == state.label
        assert restored.origin == state.origin
        assert restored.completed_tools == state.completed_tools

    def test_from_dict_missing_completed_tools_defaults_empty(self) -> None:
        data = {
            "task_id": "abc",
            "iteration": 1,
            "messages": [],
            "task": "test",
            "label": "test",
            "origin": {"channel": "cli", "chat_id": "direct"},
        }
        state = CheckpointState.from_dict(data)
        assert state.completed_tools == []

    def test_default_completed_tools(self) -> None:
        state = CheckpointState(
            task_id="x",
            iteration=0,
            messages=[],
            task="t",
            label="l",
            origin={"channel": "c", "chat_id": "d"},
        )
        assert state.completed_tools == []


class TestCheckpointStore:
    """Test checkpoint persistence."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        state = _make_state()

        store.save(state)
        loaded = store.load(state.task_id)

        assert loaded is not None
        assert loaded.task_id == state.task_id
        assert loaded.iteration == state.iteration
        assert loaded.messages == state.messages
        assert loaded.completed_tools == state.completed_tools

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        assert store.load("nonexistent") is None

    def test_save_overwrites_previous(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)

        state1 = _make_state(iteration=1)
        store.save(state1)

        state2 = _make_state(iteration=5)
        store.save(state2)

        loaded = store.load(state1.task_id)
        assert loaded is not None
        assert loaded.iteration == 5

    def test_cleanup_removes_files(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        state = _make_state()

        store.save(state)
        assert store.has_checkpoint(state.task_id)

        store.cleanup(state.task_id)
        assert not store.has_checkpoint(state.task_id)
        assert store.load(state.task_id) is None

    def test_cleanup_nonexistent_is_noop(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        store.cleanup("nonexistent")  # should not raise

    def test_has_checkpoint(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        assert not store.has_checkpoint("abc12345")

        store.save(_make_state())
        assert store.has_checkpoint("abc12345")

    def test_corrupt_checkpoint_returns_none(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        state = _make_state()
        store.save(state)

        # Corrupt the file
        path = store._checkpoint_path(state.task_id)
        path.write_text("not valid json{{{", encoding="utf-8")

        assert store.load(state.task_id) is None

    def test_incomplete_checkpoint_returns_none(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        state = _make_state()
        store.save(state)

        # Write valid JSON but missing required fields
        path = store._checkpoint_path(state.task_id)
        path.write_text('{"task_id": "abc"}', encoding="utf-8")

        assert store.load(state.task_id) is None

    def test_creates_tasks_directory(self, tmp_path: Path) -> None:
        workspace = tmp_path / "new_workspace"
        CheckpointStore(workspace)
        assert (workspace / ".tasks").exists()

    def test_multiple_tasks(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)

        state_a = _make_state(task_id="task_aaa")
        state_b = _make_state(task_id="task_bbb")

        store.save(state_a)
        store.save(state_b)

        loaded_a = store.load("task_aaa")
        loaded_b = store.load("task_bbb")

        assert loaded_a is not None and loaded_a.task_id == "task_aaa"
        assert loaded_b is not None and loaded_b.task_id == "task_bbb"

        store.cleanup("task_aaa")
        assert not store.has_checkpoint("task_aaa")
        assert store.has_checkpoint("task_bbb")

    def test_checkpoint_file_is_valid_json(self, tmp_path: Path) -> None:
        store = CheckpointStore(tmp_path)
        state = _make_state()
        store.save(state)

        path = store._checkpoint_path(state.task_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["task_id"] == "abc12345"
        assert data["iteration"] == 3
        assert isinstance(data["messages"], list)
