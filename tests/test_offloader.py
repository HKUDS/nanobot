
import sys
import json
import pytest
import os
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# --- Mock Dependencies for Environment Stability ---
# Mock litellm
sys.modules["litellm"] = MagicMock()

# Mock pydantic_settings
pydantic_settings_mock = MagicMock()
class MockBaseSettings:
    pass
pydantic_settings_mock.BaseSettings = MockBaseSettings
sys.modules["pydantic_settings"] = pydantic_settings_mock

# Mock tiktoken to ensure deterministic token counting (fallback: chars // 4)
# We mock it to raise ImportError so the offloader uses the fallback path
tiktoken_mock = MagicMock()
tiktoken_mock.get_encoding.side_effect = ImportError("Mocked missing tiktoken")
sys.modules["tiktoken"] = tiktoken_mock

# Mock other potential missing deps
sys.modules["croniter"] = MagicMock()

# Now import the code under test
from nanobot.agent.tools.offloader import (
    ToolResponseOffloader, 
    ReadArtifactTool,
    TailArtifactTool,
    SearchArtifactTool,
    ListArtifactsTool,
    CleanupArtifactsTool
)
from nanobot.config.schema import OffloadConfig


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def offloader(workspace):
    # Use small thresholds to trigger offloading easily
    config = OffloadConfig(
        enabled=True,
        threshold_tokens=50,
        threshold_bytes=200,
        max_preview_tokens=20,
        max_preview_lines=5,
        retention_days=7
    )
    return ToolResponseOffloader(workspace, config)


class TestToolResponseOffloader:
    
    def test_initialization(self, workspace):
        off = ToolResponseOffloader(workspace)
        assert off.workspace == workspace
        assert off.config.enabled is True
        # Check storage dir created
        assert (workspace / ".artifacts").exists()
        assert (workspace / ".artifacts" / ".gitignore").exists()

    def test_should_offload_thresholds(self, offloader):
        # Case 1: Small response -> False
        assert not offloader.should_offload("test_tool", "short")
        
        # Case 2: Above byte threshold
        # 201 bytes
        long_bytes = "a" * 201
        assert offloader.should_offload("test_tool", long_bytes)
        
        # Case 3: Above token threshold (fallback is len // 4)
        # 51 * 4 = 204 chars roughly for 51 tokens
        long_tokens = "aaaa" * 52 
        assert offloader.should_offload("test_tool", long_tokens)

    def test_loop_prevention(self, offloader):
        huge_response = "huge " * 1000
        # These specific tool names should NEVER be offloaded
        assert not offloader.should_offload("read_artifact", huge_response)
        assert not offloader.should_offload("tail_artifact", huge_response)
        assert not offloader.should_offload("search_artifact", huge_response)
        
    def test_offload_creates_files(self, offloader):
        content = "content " * 100
        result = offloader.offload("some_tool", content)
        
        assert result.tool_name == "some_tool"
        assert result.original_tokens > result.preview_tokens
        
        # Verify preview logic
        assert "[truncated]" in result.preview or "more lines" in result.preview
        
        # Verify file exists
        path = Path(result.artifact_path)
        assert path.exists()
        assert path.read_text() == content
        
        # Verify metadata
        meta_path = path.parent / f"{result.artifact_id}.meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["tool_name"] == "some_tool"
        assert meta["artifact_id"] == result.artifact_id

    def test_file_extensions(self, offloader):
        # JSON
        res_json = offloader.offload("t", '{"key": "value"}')
        assert res_json.artifact_path.endswith(".json")
        
        # XML
        res_xml = offloader.offload("t", '<root>val</root>')
        assert res_xml.artifact_path.endswith(".xml")
        
        # TXT
        res_txt = offloader.offload("t", 'just text')
        assert res_txt.artifact_path.endswith(".txt")

    def test_read_artifact_cache_and_disk(self, offloader):
        content = "unique content"
        offloaded = offloader.offload("t", content)
        
        # Read from memory cache (implied)
        assert offloader.read_artifact(offloaded.artifact_id) == content
        
        # Clear memory cache manually to test disk read
        offloader._artifacts.clear()
        assert offloader.read_artifact(offloaded.artifact_id) == content
        
        # Missing
        assert offloader.read_artifact("nonexistent") is None

    def test_tail_artifact(self, offloader):
        lines = [f"line {i}" for i in range(20)]
        content = "\n".join(lines)
        offloaded = offloader.offload("t", content)
        
        # Get last 5
        tail = offloader.tail_artifact(offloaded.artifact_id, 5)
        assert "line 19" in tail
        assert "line 14" not in tail
        assert "lines above" in tail
        
        # Get all (lines > total)
        tail_all = offloader.tail_artifact(offloaded.artifact_id, 50)
        assert tail_all == content

    def test_search_artifact(self, offloader):
        content = "apple\nbanana\ncherry\ndate"
        offloaded = offloader.offload("t", content)
        
        # Match
        res = offloader.search_artifact(offloaded.artifact_id, "banana")
        assert "Line 2" in res
        assert "banana" in res
        assert "apple" in res # context
        
        # No match
        res2 = offloader.search_artifact(offloaded.artifact_id, "zebra")
        assert "No matches" in res2

    def test_list_artifacts(self, offloader):
        offloader.offload("t1", "c1")
        offloader.offload("t2", "c2")
        
        stats = offloader.get_stats()
        assert stats["offload_count"] == 2
        
        items = offloader.list_artifacts()
        assert len(items) == 2
        assert items[0]["tool"] == "t1"
        assert items[1]["tool"] == "t2"
    
    def test_cleanup(self, offloader):
        # Create "old" file
        old_file = offloader.storage_path / "old.txt"
        old_file.write_text("old")
        
        # Set time to 8 days ago
        days_ago = time.time() - (8 * 24 * 3600)
        os.utime(old_file, (days_ago, days_ago))
        
        # Create "new" file
        new_file = offloader.storage_path / "new.txt"
        new_file.write_text("new")
        
        # Cleanup (default 7 days)
        deleted = offloader.cleanup()
        assert deleted == 1
        assert not old_file.exists()
        assert new_file.exists()
        
    def test_cleanup_custom_days(self, offloader):
        # Create file 2 days old
        mid_file = offloader.storage_path / "mid.txt"
        mid_file.write_text("mid")
        days_ago = time.time() - (2 * 24 * 3600)
        os.utime(mid_file, (days_ago, days_ago))
        
        # Default (7 days) should NOT delete
        assert offloader.cleanup() == 0
        assert mid_file.exists()
        
        # Custom (1 day) SHOULD delete
        assert offloader.cleanup(retention_days=1) == 1
        assert not mid_file.exists()


class TestArtifactTools:
    
    @pytest.mark.asyncio
    async def test_read_artifact_tool(self, offloader):
        tool = ReadArtifactTool(offloader)
        offloaded = offloader.offload("t", "content")
        
        # Success
        result = await tool.execute(artifact_id=offloaded.artifact_id)
        assert result == "content"
        
        # Fail
        result = await tool.execute(artifact_id="bad_id")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_tail_artifact_tool(self, offloader):
        tool = TailArtifactTool(offloader)
        offloaded = offloader.offload("t", "l1\nl2\nl3")
        
        result = await tool.execute(artifact_id=offloaded.artifact_id, lines=1)
        assert "l3" in result
        assert "l2" not in result

    @pytest.mark.asyncio
    async def test_search_artifact_tool(self, offloader):
        tool = SearchArtifactTool(offloader)
        offloaded = offloader.offload("t", "Hello World")
        
        result = await tool.execute(artifact_id=offloaded.artifact_id, query="World")
        assert "Line 1" in result

    @pytest.mark.asyncio
    async def test_list_artifacts_tool(self, offloader):
        tool = ListArtifactsTool(offloader)
        
        # Empty
        assert "No artifacts" in await tool.execute()
        
        # Populated
        offloader.offload("t", "c")
        res = await tool.execute()
        assert "Offloaded artifacts" in res
        assert "tokens saved" in res
    
    @pytest.mark.asyncio
    async def test_cleanup_tool(self, offloader):
        tool = CleanupArtifactsTool(offloader)
        
        # Mock cleanup method
        with patch.object(offloader, 'cleanup', return_value=5) as mock_cleanup:
            res = await tool.execute(retention_days=3)
            assert "Deleted 5 files" in res
            assert "older than 3 days" in res
            mock_cleanup.assert_called_with(3)
