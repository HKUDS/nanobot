"""Regression tests for the cron tool's JSON-schema / runtime contract (#3113).

The schema advertised ``required=["action"]`` while ``_add_job`` rejected empty
``message``; LLMs rationally omitted ``message`` and looped on the runtime
error. The fix keeps ``required=["action"]`` (so ``list``/``remove`` stay
callable) but states the per-action requirement in each field's description
and tightens the runtime error for ``add`` without ``message``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.registry import ToolRegistry


class _SvcStub:
    """Minimal CronService stand-in; we only exercise schema/dispatch paths."""

    def list_jobs(self, include_disabled=False):
        return []

    def get_job(self, _job_id):
        return None

    def remove_job(self, _job_id):
        return "not-found"

    def add_job(self, **kwargs):
        class _J:
            pass

        j = _J()
        j.id = "id1"
        j.name = kwargs.get("name", "x")
        return j


@pytest.fixture
def registry() -> Iterator[ToolRegistry]:
    tool = CronTool(_SvcStub(), default_timezone="UTC")
    reg = ToolRegistry()
    reg.register(tool)
    with request_context(
        RequestContext(channel="channel", chat_id="chat-id", session_key="channel:chat-id")
    ):
        yield reg


class TestSchemaContract:
    def test_list_accepted_without_message(self, registry: ToolRegistry) -> None:
        _, _, err = registry.prepare_call("cron", {"action": "list"})
        assert err is None

    def test_remove_accepted_without_message(self, registry: ToolRegistry) -> None:
        _, _, err = registry.prepare_call("cron", {"action": "remove", "job_id": "abc"})
        assert err is None

    def test_add_with_message_accepted(self, registry: ToolRegistry) -> None:
        _, _, err = registry.prepare_call(
            "cron", {"action": "add", "message": "ping", "at": "2030-01-01T00:00:00"}
        )
        assert err is None

    def test_add_without_message_surfaces_actionable_runtime_error(
        self, registry: ToolRegistry
    ) -> None:
        # Schema permits omitting message; the runtime must return a message
        # that tells the LLM exactly what's missing and how to retry, so it
        # doesn't loop like #3113 reports.
        import asyncio

        tool = registry._tools["cron"]  # type: ignore[attr-defined]
        out = asyncio.run(tool.execute(action="add", at="2030-01-01T00:00:00"))
        assert "message" in out
        assert "add" in out
        assert "Retry" in out or "retry" in out


async def test_invalid_action_returns_tool_error_and_allows_correction(registry):
    from nanobot.agent.tools.registry import is_tool_error_result

    arguments = {"action": ["list"]}
    result = await registry.execute("cron", arguments)

    assert is_tool_error_result(result)
    assert "action:" in result and "string" in result
    assert arguments == {"action": ["list"]}
    assert await registry.execute("cron", {"action": "list"}) == "No scheduled jobs."
