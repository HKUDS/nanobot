"""Tests for the Dream class — two-phase memory consolidation via AgentRunner."""

import pytest

from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.memory import Dream, MemoryStore
from nanobot.agent.runner import AgentRunResult


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path)
    s.write_soul("# Soul\n- Helpful")
    s.write_user("# User\n- Developer")
    s.write_memory("# Memory\n- Project X active")
    return s


@pytest.fixture
def mock_provider():
    p = MagicMock()
    p.chat_with_retry = AsyncMock()
    return p


@pytest.fixture
def mock_runner():
    return MagicMock()


@pytest.fixture
def dream(store, mock_provider, mock_runner):
    d = Dream(store=store, provider=mock_provider, model="test-model", max_batch_size=5)
    d._runner = mock_runner
    return d


def _make_run_result(
    stop_reason="completed",
    final_content=None,
    tool_events=None,
    usage=None,
):
    return AgentRunResult(
        final_content=final_content or stop_reason,
        stop_reason=stop_reason,
        messages=[],
        tools_used=[],
        usage={},
        tool_events=tool_events or [],
    )


class TestDreamRun:
    async def test_noop_when_no_unprocessed_history(self, dream, mock_provider, mock_runner, store):
        """Dream should not call LLM when there's nothing to process."""
        result = await dream.run()
        assert result is False
        mock_provider.chat_with_retry.assert_not_called()
        mock_runner.run.assert_not_called()

    async def test_calls_runner_for_unprocessed_entries(self, dream, mock_provider, mock_runner, store):
        """Dream should call AgentRunner when there are unprocessed history entries."""
        store.append_history("User prefers dark mode")
        mock_provider.chat_with_retry.return_value = MagicMock(content="New fact")
        mock_runner.run = AsyncMock(return_value=_make_run_result(
            tool_events=[{"name": "edit_file", "status": "ok", "detail": "memory/MEMORY.md"}],
        ))
        result = await dream.run()
        assert result is True
        mock_runner.run.assert_called_once()
        spec = mock_runner.run.call_args[0][0]
        assert spec.max_iterations == 10
        assert spec.fail_on_tool_error is False

    async def test_advances_dream_cursor(self, dream, mock_provider, mock_runner, store):
        """Dream should advance the cursor after processing."""
        store.append_history("event 1")
        store.append_history("event 2")
        mock_provider.chat_with_retry.return_value = MagicMock(content="Nothing new")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        await dream.run()
        assert store.get_last_dream_cursor() == 2

    async def test_compacts_processed_history(self, dream, mock_provider, mock_runner, store):
        """Dream should compact history after processing."""
        store.append_history("event 1")
        store.append_history("event 2")
        store.append_history("event 3")
        mock_provider.chat_with_retry.return_value = MagicMock(content="Nothing new")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        await dream.run()
        # After Dream, cursor is advanced and 3, compact keeps last max_history_entries
        entries = store.read_unprocessed_history(since_cursor=0)
        assert all(e["cursor"] > 0 for e in entries)

    async def test_run_memory_processes_isolation_slot(self, dream, mock_provider, mock_runner, store):
        """Dream.run_memory should work correctly when given an isolation slot store."""
        slot = MemoryStore(store.workspace / "slot_a")
        slot.write_soul("# Soul A in Slot A")
        slot.write_user("# User A in Slot A")
        slot.write_memory("# Memory Slot A")
        slot.append_history("slot A event 1")

        mock_provider.chat_with_retry.return_value = MagicMock(content="Analyzed slot")
        mock_runner.run = AsyncMock(return_value=_make_run_result())

        result = await dream.run_memory(store=slot)
        assert result is True
        mock_provider.chat_with_retry.assert_called_once()
        mock_runner.run.assert_called_once()
        assert slot.get_last_dream_cursor() == 1

    async def test_run_memory_slot_cursor_advances_independently(self, dream, mock_provider, mock_runner, store):
        """Each isolation slot's dream cursor should advance independently from the main store."""
        # Main store has its own history
        store.append_history("main event 1")

        # Isolation slot has separate history
        slot = MemoryStore(store.workspace / "iso_slot")
        slot.write_soul("# Soul in iso_slot")
        slot.write_user("# User in iso_slot")
        slot.write_memory("# Memory in iso_slot")
        slot.append_history("iso event 1")
        slot.append_history("iso event 2")

        mock_provider.chat_with_retry.return_value = MagicMock(content="Nothing new")
        mock_runner.run = AsyncMock(return_value=_make_run_result())

        # Process main store
        await dream.run_memory()
        assert store.get_last_dream_cursor() == 1

        # Process isolation slot separately
        await dream.run_memory(store=slot)
        assert slot.get_last_dream_cursor() == 2
        # Main store cursor unchanged
        assert store.get_last_dream_cursor() == 1

    async def test_run_memory_slot_with_no_history_is_noop(self, dream, mock_provider, mock_runner, store):
        """Dream.run_memory should return False for an isolation slot with no unprocessed history."""
        slot_empty = MemoryStore(store.workspace / "slot_empty")
        slot_empty.write_soul("# Soul")
        slot_empty.write_user("# User")
        slot_empty.write_memory("# Memory")

        result = await dream.run_memory(store=slot_empty)
        assert result is False
        mock_provider.chat_with_retry.assert_not_called()
        mock_runner.run.assert_not_called()

    async def test_run_memory_slots_iterates_all_isolation_slots(self, dream, mock_provider, mock_runner, store):
        """Dream.run_memory_slots should iterate over all isolation slots from the store."""
        slot_a = MemoryStore(store.workspace / "slot_iter_a")
        slot_a.write_soul("# Soul A")
        slot_a.write_user("# User A")
        slot_a.write_memory("# Memory A")

        slot_b = MemoryStore(store.workspace / "slot_iter_b")
        slot_b.write_soul("# Soul B")
        slot_b.write_user("# User B")
        slot_b.write_memory("# Memory B")

        store._isolation_slots = {"slot_a": slot_a, "slot_b": slot_b}

        # Mock run_memory to track calls
        dream.run_memory = AsyncMock(return_value=False)
        await dream.run_memory_slots()

        called_stores = [call.kwargs.get("store") or call.args[0] for call in dream.run_memory.call_args_list]
        assert len(called_stores) == 2
        assert slot_a in called_stores
        assert slot_b in called_stores

    async def test_run_memory_slots_returns_false_when_no_slots(self, dream, store):
        """Dream.run_memory_slots should return False when there are no isolation slots."""
        store._isolation_slots = {}
        result = await dream.run_memory_slots()
        assert result is False

    async def test_run_invokes_run_memory_slots(self, dream, mock_provider, mock_runner, store):
        """Dream.run should invoke run_memory_slots after processing the main store."""
        slot = MemoryStore(store.workspace / "slot_run")
        slot.write_soul("# Soul")
        slot.write_user("# User")
        slot.write_memory("# Memory")
        slot.append_history("slot event 1")

        store._isolation_slots = {"slot_run": slot}

        mock_provider.chat_with_retry.return_value = MagicMock(content="Analyzed")
        mock_runner.run = AsyncMock(return_value=_make_run_result())

        # Spy on run_memory_slots to verify it's called
        dream.run_memory_slots = AsyncMock(return_value=True)
        await dream.run()
        dream.run_memory_slots.assert_called_once()

    async def test_run_memory_slot_compacts_history(self, dream, mock_provider, mock_runner, store):
        """Dream.run_memory should compact history on an isolation slot after processing."""
        slot = MemoryStore(store.workspace / "slot_compact", max_history_entries=2)
        slot.write_soul("# Soul")
        slot.write_user("# User")
        slot.write_memory("# Memory")
        slot.append_history("old event 1")
        slot.append_history("old event 2")
        slot.append_history("old event 3")

        mock_provider.chat_with_retry.return_value = MagicMock(content="Nothing new")
        mock_runner.run = AsyncMock(return_value=_make_run_result())

        await dream.run_memory(store=slot)

        # After compaction with max_history_entries=2, only 2 entries should remain
        remaining = slot.read_unprocessed_history(since_cursor=0)
        assert len(remaining) <= 2

    async def test_run_memory_slot_reads_slot_files(self, dream, mock_provider, mock_runner, store):
        """Dream.run_memory should read the slot's own SOUL/USER/MEMORY files, not the main store's."""
        slot = MemoryStore(store.workspace / "slot_files")
        slot.write_soul("# Slot Soul Content")
        slot.write_user("# Slot User Content")
        slot.write_memory("# Slot Memory Content")
        slot.append_history("slot file event")

        mock_provider.chat_with_retry.return_value = MagicMock(content="Analyzed slot files")
        mock_runner.run = AsyncMock(return_value=_make_run_result())

        await dream.run_memory(store=slot)

        # Verify Phase 1 prompt contains slot-specific file contents
        phase1_call = mock_provider.chat_with_retry.call_args
        phase1_user_content = phase1_call.kwargs.get("messages", phase1_call[1].get("messages", []))[1]["content"]
        assert "Slot Soul Content" in phase1_user_content
        assert "Slot User Content" in phase1_user_content
        assert "Slot Memory Content" in phase1_user_content
        # Should NOT contain main store content
        assert "Project X active" not in phase1_user_content

