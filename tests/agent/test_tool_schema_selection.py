from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tool_schema_selection import (
    schema_list_size_bytes,
    select_model_visible_tools,
)
from nanobot.config.schema import AgentDefaults, Config, ToolsConfig
from nanobot.providers.base import LLMProvider, LLMResponse


def _schema(name: str, description: str, detail: str = "") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string", "description": detail},
                },
            },
        },
    }


def _names(definitions: list[dict]) -> list[str]:
    return [schema["function"]["name"] for schema in definitions]


def test_mcp_schema_budget_is_opt_in_and_accepts_camel_case() -> None:
    assert ToolsConfig().mcp_schema_budget_bytes == 0

    config = Config.model_validate({"tools": {"mcpSchemaBudgetBytes": 4096}})

    assert config.tools.mcp_schema_budget_bytes == 4096
    assert config.model_dump(by_alias=True)["tools"]["mcpSchemaBudgetBytes"] == 4096


def test_selection_reduces_only_mcp_schemas_and_recalls_required_tool() -> None:
    builtin = _schema("read_file", "Read a local file")
    forecast = _schema(
        "mcp_weather_forecast",
        "Return the weather forecast for a location",
        "Include hourly weather details",
    )
    history = _schema(
        "mcp_weather_history",
        "Return historical weather observations",
        "Include archived observations",
    )
    calendar = _schema("mcp_calendar_events", "List calendar events", "Date range")
    definitions = [builtin, forecast, history, calendar]
    budget = schema_list_size_bytes([forecast])

    selected = select_model_visible_tools(
        definitions,
        [{"role": "user", "content": "Show the weather forecast for Singapore"}],
        budget,
    )

    assert _names(selected) == ["read_file", "mcp_weather_forecast"]
    assert schema_list_size_bytes(selected[1:]) <= budget
    assert schema_list_size_bytes(selected[1:]) < schema_list_size_bytes(definitions[1:])


def test_selection_is_deterministic_for_latest_user_message() -> None:
    calendar = _schema("mcp_calendar_events", "List calendar events")
    weather = _schema("mcp_weather_forecast", "Return a weather forecast")
    definitions = [calendar, weather]
    messages = [
        {"role": "user", "content": "Show calendar events"},
        {"role": "assistant", "content": "What next?"},
        {"role": "user", "content": "Now show the weather forecast"},
    ]
    budget = schema_list_size_bytes([weather])

    first = select_model_visible_tools(definitions, messages, budget)
    second = select_model_visible_tools(definitions, messages, budget)

    assert _names(first) == ["mcp_weather_forecast"]
    assert first == second


@pytest.mark.parametrize(
    "message,budget",
    [
        ("Help me with this task", 100),
        ("Show the weather forecast", 1),
    ],
)
def test_selection_fails_open_when_relevance_or_budget_is_unsafe(
    message: str,
    budget: int,
) -> None:
    definitions = [
        _schema("mcp_weather_forecast", "Return a weather forecast"),
        _schema("mcp_calendar_events", "List calendar events"),
    ]

    selected = select_model_visible_tools(
        definitions,
        [{"role": "user", "content": message}],
        budget,
    )

    assert selected is definitions


def test_selection_fails_open_for_server_name_without_an_operation() -> None:
    definitions = [
        _schema("mcp_github_create_issue", "Create an issue in a repository"),
        _schema("mcp_github_merge_pull_request", "Merge a pull request"),
    ]

    selected = select_model_visible_tools(
        definitions,
        [{"role": "user", "content": "Use GitHub for this"}],
        schema_list_size_bytes([definitions[0]]),
    )

    assert selected is definitions


@pytest.mark.asyncio
async def test_runner_sends_budgeted_view_without_changing_registry() -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="done"))
    builtin = _schema("read_file", "Read a local file")
    weather = _schema("mcp_weather_forecast", "Return a weather forecast")
    calendar = _schema("mcp_calendar_events", "List calendar events")
    definitions = [builtin, weather, calendar]
    tools = MagicMock()
    tools.get_definitions.return_value = definitions

    await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "Show the weather forecast"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
        mcp_schema_budget_bytes=schema_list_size_bytes([weather]),
    ))

    sent = provider.chat_with_retry.await_args.kwargs["tools"]
    assert _names(sent) == ["read_file", "mcp_weather_forecast"]
    assert tools.get_definitions.return_value is definitions
