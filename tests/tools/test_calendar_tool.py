"""Tests for calendar tool."""

import json

import pytest

from nanobot.agent.tools.calendar import CalendarTool


@pytest.mark.asyncio
async def test_calendar_providers(tmp_path) -> None:
    tool = CalendarTool(workspace=tmp_path, default_timezone="Asia/Shanghai")
    result = await tool.execute(action="providers")
    data = json.loads(result)
    assert data["local"]["configured"] is True
    assert list(data.keys()) == ["local"]


@pytest.mark.asyncio
async def test_calendar_create_list_conflict_update_delete(tmp_path) -> None:
    tool = CalendarTool(workspace=tmp_path, default_timezone="Asia/Shanghai")

    created = json.loads(
        await tool.execute(
            action="create",
            title="研发评审",
            start_at="2026-04-12T10:00:00+08:00",
            end_at="2026-04-12T11:00:00+08:00",
            attendees=["alice", "bob"],
        )
    )
    event_id = created["event"]["id"]

    listed = json.loads(await tool.execute(action="list"))
    assert len(listed["events"]) == 1
    assert listed["events"][0]["title"] == "研发评审"

    conflicts = json.loads(
        await tool.execute(
            action="conflicts",
            start_at="2026-04-12T10:30:00+08:00",
            end_at="2026-04-12T11:30:00+08:00",
        )
    )
    assert len(conflicts["conflicts"]) == 1
    assert conflicts["conflicts"][0]["id"] == event_id

    slots = json.loads(
        await tool.execute(
            action="find_free_slots",
            start_at="2026-04-12T09:00:00+08:00",
            end_at="2026-04-12T13:00:00+08:00",
            duration_minutes=30,
            step_minutes=30,
            limit=3,
        )
    )
    assert len(slots["slots"]) >= 1
    assert slots["slots"][0]["duration_minutes"] == 30

    updated = json.loads(
        await tool.execute(
            action="update",
            event_id=event_id,
            updates={"title": "研发评审-改"},
        )
    )
    assert updated["event"]["title"] == "研发评审-改"

    deleted = json.loads(await tool.execute(action="delete", event_id=event_id))
    assert deleted["deleted"] is True

    relisted = json.loads(await tool.execute(action="list"))
    assert relisted["events"] == []


@pytest.mark.asyncio
async def test_calendar_error_code_payload(tmp_path) -> None:
    tool = CalendarTool(workspace=tmp_path, default_timezone="Asia/Shanghai")
    result = await tool.execute(action="create")
    assert result.startswith("Error: ")
    payload = json.loads(result[len("Error: "):])
    assert payload["error"]["code"] == "CAL_INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_calendar_invalid_datetime_returns_invalid_argument(tmp_path) -> None:
    tool = CalendarTool(workspace=tmp_path, default_timezone="Asia/Shanghai")
    result = await tool.execute(
        action="create",
        title="bad",
        start_at="not-time",
        end_at="2026-04-12T11:00:00+08:00",
    )
    assert result.startswith("Error: ")
    payload = json.loads(result[len("Error: "):])
    assert payload["error"]["code"] == "CAL_INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_calendar_update_unknown_field_returns_invalid_argument(tmp_path) -> None:
    tool = CalendarTool(workspace=tmp_path, default_timezone="Asia/Shanghai")
    created = json.loads(
        await tool.execute(
            action="create",
            title="研发评审",
            start_at="2026-04-12T10:00:00+08:00",
            end_at="2026-04-12T11:00:00+08:00",
        )
    )
    event_id = created["event"]["id"]

    result = await tool.execute(
        action="update",
        event_id=event_id,
        updates={"foo": "bar"},
    )
    assert result.startswith("Error: ")
    payload = json.loads(result[len("Error: "):])
    assert payload["error"]["code"] == "CAL_INVALID_ARGUMENT"
    assert payload["error"]["details"]["unknown_fields"] == ["foo"]


@pytest.mark.asyncio
async def test_calendar_list_calendars_local(tmp_path) -> None:
    tool = CalendarTool(workspace=tmp_path, default_timezone="Asia/Shanghai")
    result = json.loads(await tool.execute(action="list_calendars"))
    assert result["calendars"][0]["id"] == "default"


def test_calendar_parameters_are_plain_json_schema(tmp_path) -> None:
    tool = CalendarTool(workspace=tmp_path, default_timezone="Asia/Shanghai")
    params = tool.parameters
    assert isinstance(params, dict)
    assert params["type"] == "object"
    assert params["properties"]["event_description"]["type"] == ["string", "null"]
