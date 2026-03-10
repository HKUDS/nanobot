from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import MemoryStore
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_session(message_count: int = 30):
    class _Session:
        def __init__(self) -> None:
            self.messages = [
                {"role": "user", "content": f"msg{i}", "timestamp": "2026-03-09T12:34:56"}
                for i in range(message_count)
            ]
            self.last_consolidated = 0

    return _Session()


@pytest.mark.asyncio
async def test_consolidation_writes_daily_note_and_core_memory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_memory",
                    arguments={
                        "history_entry": "[2026-03-09 12:34] Investigated memory policy and chose daily notes.",
                        "memory_update": "# Memory\n- Prefer daily note archival for episodic memory.\n",
                    },
                )
            ],
        )
    )

    result = await store.consolidate(_make_session(message_count=60), provider, "test-model", memory_window=50)

    assert result is True
    assert store.memory_file.read_text(encoding="utf-8").startswith("# Memory")
    daily_note = store.memory_dir / "2026-03-09.md"
    assert daily_note.exists()
    assert "Investigated memory policy" in daily_note.read_text(encoding="utf-8")


def test_context_builder_injects_only_core_memory_not_daily_notes(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("# Memory\n- User prefers concise updates.\n", encoding="utf-8")
    (memory_dir / "2026-03-09.md").write_text("[2026-03-09 12:00] Temporary daily note.\n", encoding="utf-8")

    prompt = ContextBuilder(tmp_path).build_system_prompt()

    assert "User prefers concise updates" in prompt
    assert "Temporary daily note" not in prompt


def test_memory_search_and_get_cover_daily_and_core_memory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.write_long_term("# Memory\n- User prefers concise updates.\n")
    store.write_daily_note("2026-03-09", "[2026-03-09 12:00] Investigated memory policy for OpenClaw parity.")

    search_results = store.search("OpenClaw parity", limit=5)

    assert len(search_results) == 1
    assert search_results[0]["path"] == "memory/2026-03-09.md"
    assert "OpenClaw parity" in search_results[0]["snippet"]

    document = store.get_document("memory/2026-03-09.md")
    assert "Investigated memory policy" in document


def test_memory_get_rejects_paths_outside_memory_dir(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("nope", encoding="utf-8")

    with pytest.raises(PermissionError):
        store.get_document(str(outside_file))


@pytest.mark.asyncio
async def test_agent_loop_registers_memory_recall_tools(tmp_path: Path) -> None:
    provider = AsyncMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")

    assert loop.tools.has("memory_search")
    assert loop.tools.has("memory_get")

    store = MemoryStore(tmp_path)
    store.write_daily_note("2026-03-09", "[2026-03-09 12:00] Investigated memory policy for OpenClaw parity.")

    search_result = await loop.tools.execute("memory_search", {"query": "OpenClaw parity"})
    get_result = await loop.tools.execute("memory_get", {"path": "memory/2026-03-09.md"})

    assert "2026-03-09.md" in search_result
    assert "Investigated memory policy" in get_result
