"""Tests for the tool authorization / permission layer."""

import asyncio
import json
import pytest
import sys
import os

# Add nanobot to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from nanobot.agent.tools.permissions import ToolPermissionManager
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.base import Tool


# ── Fixtures ────────────────────────────────────────────────────────


class MockTool(Tool):
    """Minimal tool for testing."""

    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Mock {self._name}"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, **kwargs) -> str:
        return f"EXECUTED:{self._name}:{kwargs.get('text', '')}"


# ── ToolPermissionManager tests ─────────────────────────────────────


class TestToolPermissionManager:
    def test_unlisted_tool_auto_approves(self):
        mgr = ToolPermissionManager(
            require_approval_tools={"mcp_composio_REDDIT_CREATE_REDDIT_POST"},
        )
        assert mgr.should_auto_approve("read_file") is True
        assert mgr.should_auto_approve("web_search") is True
        assert mgr.should_auto_approve("exec") is True

    def test_listed_tool_requires_approval(self):
        mgr = ToolPermissionManager(
            require_approval_tools={"mcp_composio_REDDIT_CREATE_REDDIT_POST", "message"},
        )
        assert mgr.should_auto_approve("mcp_composio_REDDIT_CREATE_REDDIT_POST") is False
        assert mgr.should_auto_approve("message") is False

    def test_user_override_auto_approved_wins(self):
        mgr = ToolPermissionManager(
            require_approval_tools={"mcp_composio_REDDIT_CREATE_REDDIT_POST"},
            user_overrides={"mcp_composio_REDDIT_CREATE_REDDIT_POST": "auto_approved"},
        )
        assert mgr.should_auto_approve("mcp_composio_REDDIT_CREATE_REDDIT_POST") is True

    def test_user_override_require_approval_on_unlisted(self):
        mgr = ToolPermissionManager(
            require_approval_tools=set(),
            user_overrides={"exec": "require_approval"},
        )
        # User override takes precedence — can add require_approval beyond template
        assert mgr.should_auto_approve("exec") is False

    def test_empty_sets_all_auto_approve(self):
        mgr = ToolPermissionManager(require_approval_tools=set())
        assert mgr.should_auto_approve("anything") is True

    def test_make_proposal_returns_valid_json(self):
        result = ToolPermissionManager.make_proposal(
            "mcp_composio_REDDIT_CREATE_REDDIT_POST",
            {"title": "Test", "body": "Hello"},
        )
        parsed = json.loads(result)
        assert parsed["status"] == "proposed"
        assert parsed["tool"] == "mcp_composio_REDDIT_CREATE_REDDIT_POST"
        assert parsed["arguments"]["title"] == "Test"
        assert "approval" in parsed["message"].lower()


# ── ToolRegistry permission integration tests ───────────────────────


class TestRegistryPermissions:
    @pytest.fixture
    def registry(self):
        r = ToolRegistry()
        r.register(MockTool("read_file"))
        r.register(MockTool("mcp_composio_REDDIT_CREATE_REDDIT_POST"))
        r.register(MockTool("message"))
        r.register(MockTool("web_search"))
        return r

    def test_no_permissions_all_execute(self, registry: ToolRegistry):
        result = asyncio.get_event_loop().run_until_complete(
            registry.execute("mcp_composio_REDDIT_CREATE_REDDIT_POST", {"text": "hi"})
        )
        assert "EXECUTED:" in result
        assert registry.get_and_clear_proposals() == []

    def test_require_approval_returns_proposal(self, registry: ToolRegistry):
        mgr = ToolPermissionManager(
            require_approval_tools={"mcp_composio_REDDIT_CREATE_REDDIT_POST"},
        )
        registry.set_permissions(mgr)

        result = asyncio.get_event_loop().run_until_complete(
            registry.execute("mcp_composio_REDDIT_CREATE_REDDIT_POST", {"text": "post content"})
        )

        parsed = json.loads(result)
        assert parsed["status"] == "proposed"
        assert parsed["tool"] == "mcp_composio_REDDIT_CREATE_REDDIT_POST"
        assert parsed["arguments"]["text"] == "post content"

    def test_auto_approved_tool_still_executes(self, registry: ToolRegistry):
        mgr = ToolPermissionManager(
            require_approval_tools={"mcp_composio_REDDIT_CREATE_REDDIT_POST"},
        )
        registry.set_permissions(mgr)

        result = asyncio.get_event_loop().run_until_complete(
            registry.execute("read_file", {"text": "test.txt"})
        )
        assert "EXECUTED:read_file:test.txt" in result

    def test_proposals_accumulate(self, registry: ToolRegistry):
        mgr = ToolPermissionManager(
            require_approval_tools={"mcp_composio_REDDIT_CREATE_REDDIT_POST", "message"},
        )
        registry.set_permissions(mgr)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(registry.execute("mcp_composio_REDDIT_CREATE_REDDIT_POST", {"text": "post 1"}))
        loop.run_until_complete(registry.execute("message", {"text": "msg 1"}))
        loop.run_until_complete(registry.execute("read_file", {"text": "file"}))  # auto-approved
        loop.run_until_complete(registry.execute("mcp_composio_REDDIT_CREATE_REDDIT_POST", {"text": "post 2"}))

        proposals = registry.get_and_clear_proposals()
        assert len(proposals) == 3
        assert proposals[0]["tool"] == "mcp_composio_REDDIT_CREATE_REDDIT_POST"
        assert proposals[0]["arguments"]["text"] == "post 1"
        assert proposals[1]["tool"] == "message"
        assert proposals[2]["arguments"]["text"] == "post 2"

    def test_get_and_clear_resets(self, registry: ToolRegistry):
        mgr = ToolPermissionManager(require_approval_tools={"message"})
        registry.set_permissions(mgr)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(registry.execute("message", {"text": "hi"}))

        assert len(registry.get_and_clear_proposals()) == 1
        assert len(registry.get_and_clear_proposals()) == 0

    def test_set_permissions_clears_proposals(self, registry: ToolRegistry):
        mgr = ToolPermissionManager(require_approval_tools={"message"})
        registry.set_permissions(mgr)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(registry.execute("message", {"text": "hi"}))
        assert len(registry._proposals) == 1

        registry.set_permissions(mgr)
        assert len(registry._proposals) == 0

    def test_user_override_auto_approved_executes(self, registry: ToolRegistry):
        mgr = ToolPermissionManager(
            require_approval_tools={"message"},
            user_overrides={"message": "auto_approved"},
        )
        registry.set_permissions(mgr)

        result = asyncio.get_event_loop().run_until_complete(
            registry.execute("message", {"text": "hello"})
        )
        assert "EXECUTED:message:hello" in result
        assert registry.get_and_clear_proposals() == []
