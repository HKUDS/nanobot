"""Google Sheets tool bounds and allowlist."""

from __future__ import annotations

import json
from typing import Any

import pytest

from nanobot.agent.tools.drive import DriveToolConfig
from nanobot.agent.tools.sheets import (
    GoogleSheetsTool,
    SheetsToolConfig,
    _SheetsClient,
    append_sheet_range,
    bounded_sheet_range,
    parse_sheet_values,
    resolve_sheets_credentials_path,
)


class _Request:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def execute(self) -> dict[str, Any]:
        return self.payload


class _Values:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, **kwargs: object) -> _Request:
        self.calls.append(("get", dict(kwargs)))
        return _Request({"range": "Sheet1!A1:B1", "values": [["Rent", 12]]})

    def update(self, **kwargs: object) -> _Request:
        self.calls.append(("update", dict(kwargs)))
        return _Request({"updatedRange": "Sheet1!A1:B1", "updatedRows": 1, "updatedCells": 2})

    def append(self, **kwargs: object) -> _Request:
        self.calls.append(("append", dict(kwargs)))
        return _Request({"updates": {"updatedRange": "Sheet1!A2", "updatedRows": 1, "updatedCells": 2}})


class _Spreadsheets:
    def __init__(self) -> None:
        self.values_api = _Values()

    def get(self, **kwargs: object) -> _Request:
        return _Request({
            "properties": {"title": "Budget"},
            "sheets": [{
                "properties": {
                    "title": "Sheet1",
                    "sheetId": 0,
                    "gridProperties": {"rowCount": 20, "columnCount": 4},
                },
            }],
        })

    def values(self) -> _Values:
        return self.values_api


class _Service:
    def __init__(self) -> None:
        self.api = _Spreadsheets()

    def spreadsheets(self) -> _Spreadsheets:
        return self.api


def _tool() -> tuple[GoogleSheetsTool, _Service]:
    service = _Service()
    sheets = SheetsToolConfig(
        enabled=True,
        spreadsheet_ids=["sheet-one"],
        max_read_rows=5,
        max_write_cells=10,
    )
    tool = GoogleSheetsTool(sheets=sheets, drive=DriveToolConfig())
    tool._client = _SheetsClient(
        service,
        frozenset({"sheet-one"}),
        max_read_rows=5,
        max_write_cells=10,
    )
    return tool, service


def test_bounded_range_rejects_open_columns() -> None:
    with pytest.raises(ValueError, match="bounded A1"):
        bounded_sheet_range("Sheet1!A:C")
    text, rows, cols = bounded_sheet_range("Sheet1!A1:B2")
    assert text == "Sheet1!A1:B2"
    assert (rows, cols) == (2, 2)
    assert append_sheet_range("Sheet1!A:C") == "Sheet1!A:C"


def test_parse_sheet_values_keeps_typed_cells_and_rejects_objects() -> None:
    rows = parse_sheet_values('[["Rent", 12, true, null]]', max_rows=5, max_cells=10)
    assert rows == [["Rent", 12, True, None]]
    with pytest.raises(ValueError, match="strings, numbers"):
        parse_sheet_values('[[{"a": 1}]]', max_rows=5, max_cells=10)


def test_credentials_fall_back_to_the_drive_key(tmp_path) -> None:
    key = tmp_path / "sa.json"
    key.write_text("{}", encoding="utf-8")
    path = resolve_sheets_credentials_path(
        SheetsToolConfig(),
        DriveToolConfig(credentials_path=str(key)),
    )
    assert path == key.resolve()


@pytest.mark.asyncio
async def test_read_rejects_a_spreadsheet_outside_the_allowlist() -> None:
    tool, _service = _tool()
    result = await tool.execute(action="read", spreadsheet_id="other-sheet", range="A1")
    assert result.startswith("Error:")
    assert "not in the configured" in result


@pytest.mark.asyncio
async def test_update_sends_user_entered_values_that_fit_the_range() -> None:
    tool, service = _tool()
    result = await tool.execute(
        action="update",
        range="Sheet1!A1:B1",
        values_json='[["Rent", 12]]',
    )
    assert not result.startswith("Error:")
    payload = json.loads(result)
    assert payload["updatedCells"] == 2
    _name, kwargs = service.api.values_api.calls[-1]
    assert kwargs["valueInputOption"] == "USER_ENTERED"
    assert kwargs["body"] == {"values": [["Rent", 12]]}

    too_wide = await tool.execute(action="update", range="A1", values_json='[["a", "b"]]')
    assert too_wide.startswith("Error:")
    assert "do not fit" in too_wide


@pytest.mark.asyncio
async def test_append_accepts_a_column_range() -> None:
    tool, service = _tool()
    result = await tool.execute(action="append", range="Sheet1!A:B", values_json='[["Rent", 12]]')
    assert not result.startswith("Error:")
    _name, kwargs = service.api.values_api.calls[-1]
    assert kwargs["insertDataOption"] == "INSERT_ROWS"
    assert kwargs["range"] == "Sheet1!A:B"
