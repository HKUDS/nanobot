"""Tests for HeartbeatDecisionTool and EvaluateNotificationTool (LLM-only virtual tools)."""

import pytest

from nanobot.agent.tools.evaluate_notification import (
    EVALUATE_NOTIFICATION_TOOL_DEFINITIONS,
    EvaluateNotificationTool,
)
from nanobot.agent.tools.heartbeat import (
    HEARTBEAT_DECISION_TOOL_DEFINITIONS,
    HeartbeatDecisionTool,
)


class TestHeartbeatDecisionTool:
    def test_to_schema_is_openai_function_tool(self) -> None:
        tool = HeartbeatDecisionTool()
        envelope = tool.to_schema()
        assert envelope["type"] == "function"
        function = envelope["function"]
        assert function["name"] == "heartbeat"
        assert function["description"]
        params = function["parameters"]
        assert params["type"] == "object"
        assert "action" in params["required"]
        assert params["properties"]["action"]["enum"] == ["skip", "run"]
        assert "tasks" in params["properties"]

    def test_definitions_list_matches_single_to_schema(self) -> None:
        tool = HeartbeatDecisionTool()
        assert HEARTBEAT_DECISION_TOOL_DEFINITIONS == [tool.to_schema()]

    def test_read_only(self) -> None:
        assert HeartbeatDecisionTool().read_only is True

    @pytest.mark.parametrize(
        ("payload", "expect_ok"),
        [
            ({"action": "skip"}, True),
            ({"action": "run", "tasks": "do things"}, True),
            ({}, False),
            ({"action": "maybe"}, False),
        ],
    )
    def test_validate_params(self, payload: dict, expect_ok: bool) -> None:
        errors = HeartbeatDecisionTool().validate_params(payload)
        assert (len(errors) == 0) == expect_ok

    @pytest.mark.asyncio
    async def test_execute_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            await HeartbeatDecisionTool().execute(action="skip")


class TestEvaluateNotificationTool:
    def test_to_schema_is_openai_function_tool(self) -> None:
        tool = EvaluateNotificationTool()
        envelope = tool.to_schema()
        assert envelope["type"] == "function"
        function = envelope["function"]
        assert function["name"] == "evaluate_notification"
        assert function["description"]
        params = function["parameters"]
        assert params["type"] == "object"
        assert "should_notify" in params["required"]
        assert params["properties"]["should_notify"]["type"] == "boolean"

    def test_definitions_list_matches_single_to_schema(self) -> None:
        tool = EvaluateNotificationTool()
        assert EVALUATE_NOTIFICATION_TOOL_DEFINITIONS == [tool.to_schema()]

    def test_read_only(self) -> None:
        assert EvaluateNotificationTool().read_only is True

    @pytest.mark.parametrize(
        ("payload", "expect_ok"),
        [
            ({"should_notify": True}, True),
            ({"should_notify": False, "reason": "routine"}, True),
            ({}, False),
        ],
    )
    def test_validate_params(self, payload: dict, expect_ok: bool) -> None:
        errors = EvaluateNotificationTool().validate_params(payload)
        assert (len(errors) == 0) == expect_ok

    @pytest.mark.asyncio
    async def test_execute_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            await EvaluateNotificationTool().execute(should_notify=True)
