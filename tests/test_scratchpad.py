"""Tests for the session Scratchpad and scratchpad tools.

Covers:
- Write/read roundtrip
- List entries
- Concurrent writes
- Eviction on overflow
- Clear
- ScratchpadWriteTool / ScratchpadReadTool
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from nanobot.agent.scratchpad import Scratchpad
from nanobot.agent.tools.scratchpad import ScratchpadReadTool, ScratchpadWriteTool

# ---------------------------------------------------------------------------
# Scratchpad core
# ---------------------------------------------------------------------------


class TestScratchpad:
    async def test_write_read_roundtrip(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        entry_id = await pad.write(role="code", label="test", content="hello world")
        assert len(entry_id) == 8
        result = pad.read(entry_id)
        assert "hello world" in result
        assert "code" in result

    async def test_read_all(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        await pad.write(role="code", label="first", content="aaa")
        await pad.write(role="research", label="second", content="bbb")
        result = pad.read()
        assert "first" in result
        assert "second" in result

    async def test_read_nonexistent(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        result = pad.read("nonexistent")
        assert result is None

    async def test_read_empty(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        result = pad.read()
        assert result is None

    async def test_list_entries(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        await pad.write(role="a", label="entry1", content="x")
        await pad.write(role="b", label="entry2", content="y")
        entries = pad.list_entries()
        assert len(entries) == 2
        assert entries[0]["role"] == "a"
        assert entries[1]["label"] == "entry2"

    async def test_eviction_on_overflow(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path, max_entries=3)
        for i in range(5):
            await pad.write(role="r", label=f"e{i}", content=f"c{i}")
        entries = pad.list_entries()
        assert len(entries) == 3
        # Oldest should be evicted
        labels = [e["label"] for e in entries]
        assert "e0" not in labels
        assert "e1" not in labels
        assert "e4" in labels

    async def test_clear(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        await pad.write(role="r", label="x", content="y")
        await pad.clear()
        assert pad.list_entries() == []
        assert pad.read() is None

    async def test_concurrent_writes(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)

        async def writer(i: int) -> str:
            return await pad.write(role="w", label=f"item{i}", content=f"data{i}")

        ids = await asyncio.gather(*[writer(i) for i in range(10)])
        assert len(set(ids)) == 10  # All unique IDs
        assert len(pad.list_entries()) == 10

    async def test_persistence(self, tmp_path: Path) -> None:
        """Data survives across Scratchpad instances."""
        pad1 = Scratchpad(tmp_path)
        entry_id = await pad1.write(role="r", label="persist", content="data")

        # Create new instance pointing to same directory
        pad2 = Scratchpad(tmp_path)
        result = pad2.read(entry_id)
        assert "data" in result


# ---------------------------------------------------------------------------
# Scratchpad Tools
# ---------------------------------------------------------------------------


class TestScratchpadWriteTool:
    async def test_write_returns_entry_id(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        tool = ScratchpadWriteTool(pad)
        result = await tool.execute(label="test", content="hello")
        assert result.success
        assert "scratchpad" in result.output.lower()

    async def test_tool_metadata(self) -> None:
        pad = Scratchpad(Path("/tmp/test"))
        tool = ScratchpadWriteTool(pad)
        assert tool.name == "write_scratchpad"
        assert not tool.readonly


class TestScratchpadReadTool:
    async def test_read_all(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        await pad.write(role="r", label="x", content="y")
        tool = ScratchpadReadTool(pad)
        result = await tool.execute()
        assert result.success
        assert "x" in result.output

    async def test_read_specific(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        eid = await pad.write(role="r", label="specific", content="detail")
        tool = ScratchpadReadTool(pad)
        result = await tool.execute(entry_id=eid)
        assert result.success
        assert "detail" in result.output

    async def test_tool_metadata(self) -> None:
        pad = Scratchpad(Path("/tmp/test"))
        tool = ScratchpadReadTool(pad)
        assert tool.name == "read_scratchpad"
        assert tool.readonly
