"""Google Sheets tool (service account, shared spreadsheets, read and update)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Protocol, cast

from nanobot.agent.tools._google import (
    GoogleDeps,
    build_google_service,
    require_google_deps,
    resolve_credentials_path,
    service_account_email_hint,
)
from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.drive_config import DriveToolConfig
from nanobot.agent.tools.schema import (
    StringSchema,
    tool_parameters_schema,
)
from nanobot.agent.tools.sheets_config import SheetsToolConfig

_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
_SHEETS_HTTP_TIMEOUT_SECONDS = 15
_LABEL = "Google Sheets"
_MAX_CELL_CHARS = 50_000
_SHEET_PREFIX = r"(?:'[^']{1,100}'|[A-Za-z0-9_][A-Za-z0-9_ ]{0,80})!"
_CELL = r"[A-Za-z]{1,3}[1-9][0-9]{0,6}"
_BOUNDED_RANGE = re.compile(rf"^(?:{_SHEET_PREFIX})?{_CELL}(?::{_CELL})?$")
_APPEND_RANGE = re.compile(
    rf"^(?:{_SHEET_PREFIX})?(?:{_CELL}|[A-Za-z]{{1,3}}(?::[A-Za-z]{{1,3}})?)?$"
)


class _SheetsRequest(Protocol):
    def execute(self) -> object: ...


class _SheetsValues(Protocol):
    def get(self, **kwargs: object) -> _SheetsRequest: ...
    def update(self, **kwargs: object) -> _SheetsRequest: ...
    def append(self, **kwargs: object) -> _SheetsRequest: ...


class _SheetsSpreadsheets(Protocol):
    def get(self, **kwargs: object) -> _SheetsRequest: ...
    def values(self) -> _SheetsValues: ...


class _SheetsService(Protocol):
    def spreadsheets(self) -> _SheetsSpreadsheets: ...


def _require_google_deps() -> GoogleDeps:
    return require_google_deps("Google Sheets", "sheets")


def resolve_sheets_credentials_path(
    sheets: SheetsToolConfig,
    drive: DriveToolConfig,
) -> Path:
    raw = (sheets.credentials_path or "").strip() or (drive.credentials_path or "").strip()
    if not raw:
        raise ValueError(
            "No service account key is configured. Set tools.sheets.credentialsPath or tools.drive.credentialsPath."
        )
    path = resolve_credentials_path(raw)
    if not path.is_file():
        raise ValueError(f"Service account key not found: {path}")
    return path


def sheets_service_account_email(sheets: SheetsToolConfig, drive: DriveToolConfig) -> str | None:
    try:
        path = resolve_sheets_credentials_path(sheets, drive)
    except ValueError:
        return None
    return service_account_email_hint(path)


def _column_index(letters: str) -> int:
    value = 0
    for char in letters.upper():
        value = value * 26 + (ord(char) - 64)
    return value


def bounded_sheet_range(value: str) -> tuple[str, int, int]:
    text = value.strip()
    if _BOUNDED_RANGE.fullmatch(text) is None:
        raise ValueError("range must be a bounded A1 range such as Sheet1!A1:C20")
    parts = re.findall(r"([A-Za-z]{1,3})([1-9][0-9]{0,6})", text.split("!", 1)[-1])
    if not parts:
        raise ValueError("range must be a bounded A1 range such as Sheet1!A1:C20")
    start_col, start_row = parts[0]
    end_col, end_row = parts[-1]
    rows = int(end_row) - int(start_row) + 1
    cols = _column_index(end_col) - _column_index(start_col) + 1
    if rows < 1 or cols < 1:
        raise ValueError("range end must be below and to the right of the start")
    return text, rows, cols


def append_sheet_range(value: str) -> str:
    text = value.strip()
    if _APPEND_RANGE.fullmatch(text) is None:
        raise ValueError("append range must look like Sheet1!A1 or Sheet1!A:C")
    return text


def parse_sheet_values(raw: str, *, max_rows: int, max_cells: int) -> list[list[Any]]:
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("values_json must be a JSON array of rows") from exc
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("values_json must be a non-empty JSON array of rows")
    rows = cast(list[object], parsed)
    if len(rows) > max_rows:
        raise ValueError(f"values_json has {len(rows)} rows; the limit is {max_rows}")
    normalized: list[list[Any]] = []
    cells = 0
    for row in rows:
        if not isinstance(row, list):
            raise ValueError("each values_json row must be an array")
        items = cast(list[object], row)
        parsed_row: list[Any] = []
        for item in items:
            parsed_row.append(_cell_value(item))
            cells += 1
            if cells > max_cells:
                raise ValueError(f"values_json has more than {max_cells} cells")
        normalized.append(parsed_row)
    return normalized


def _cell_value(value: object) -> Any:
    if value is None or isinstance(value, str | bool):
        if isinstance(value, str) and len(value) > _MAX_CELL_CHARS:
            raise ValueError(f"a cell is longer than {_MAX_CELL_CHARS} characters")
        return value
    if isinstance(value, int | float):
        if isinstance(value, float) and value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("cell values must be finite numbers")
        return value
    raise ValueError("cell values must be strings, numbers, booleans, or null")


def _mapping(value: object, operation: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Sheets API returned an invalid {operation} response")
    return {str(key): item for key, item in cast(dict[object, object], value).items()}


class _SheetsClient:
    def __init__(
        self,
        service: _SheetsService,
        allowed: frozenset[str],
        *,
        max_read_rows: int,
        max_write_cells: int,
    ) -> None:
        self._service = service
        self._allowed = allowed
        self._max_read_rows = max_read_rows
        self._max_write_cells = max_write_cells

    def _require_allowed(self, spreadsheet_id: str) -> str:
        sheet_id = spreadsheet_id.strip()
        if sheet_id not in self._allowed:
            raise PermissionError(
                f"Spreadsheet '{sheet_id}' is not in the configured Google Sheets list"
            )
        return sheet_id

    def metadata(self, spreadsheet_id: str) -> dict[str, object]:
        sheet_id = self._require_allowed(spreadsheet_id)
        response = _mapping(
            self._service.spreadsheets().get(
                spreadsheetId=sheet_id,
                fields="properties.title,sheets.properties(title,sheetId,gridProperties(rowCount,columnCount))",
            ).execute(),
            "spreadsheet",
        )
        properties = response.get("properties")
        title = ""
        if isinstance(properties, dict):
            raw_title = cast(dict[str, object], properties).get("title")
            title = raw_title if isinstance(raw_title, str) else ""
        sheets: list[dict[str, object]] = []
        raw_sheets = response.get("sheets")
        if isinstance(raw_sheets, list):
            for item in cast(list[object], raw_sheets):
                if not isinstance(item, dict):
                    continue
                sheet_props = cast(dict[str, object], item).get("properties")
                if not isinstance(sheet_props, dict):
                    continue
                props = cast(dict[str, object], sheet_props)
                grid = props.get("gridProperties")
                row_count = None
                column_count = None
                if isinstance(grid, dict):
                    grid_values = cast(dict[str, object], grid)
                    if isinstance(grid_values.get("rowCount"), int):
                        row_count = grid_values["rowCount"]
                    if isinstance(grid_values.get("columnCount"), int):
                        column_count = grid_values["columnCount"]
                sheet_title = props.get("title")
                sheets.append({
                    "title": sheet_title if isinstance(sheet_title, str) else "",
                    "sheetId": props.get("sheetId"),
                    "rowCount": row_count,
                    "columnCount": column_count,
                })
        return {"spreadsheetId": sheet_id, "title": title, "sheets": sheets}

    def list_configured(self) -> list[dict[str, object]]:
        return [self.metadata(sheet_id) for sheet_id in sorted(self._allowed)]

    def read(self, spreadsheet_id: str, range_name: str) -> dict[str, object]:
        sheet_id = self._require_allowed(spreadsheet_id)
        normalized, rows, cols = bounded_sheet_range(range_name)
        self._check_box(rows, cols)
        response = _mapping(
            self._service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range=normalized,
            ).execute(),
            "values",
        )
        values = response.get("values")
        grid = cast(list[object], values) if isinstance(values, list) else []
        truncated = len(grid) > self._max_read_rows
        if truncated:
            grid = grid[: self._max_read_rows]
        return {
            "spreadsheetId": sheet_id,
            "range": response.get("range") or normalized,
            "values": grid,
            "truncated": truncated,
        }

    def update(self, spreadsheet_id: str, range_name: str, values: list[list[Any]]) -> dict[str, object]:
        sheet_id = self._require_allowed(spreadsheet_id)
        normalized, rows, cols = bounded_sheet_range(range_name)
        self._check_box(rows, cols)
        if len(values) > rows or any(len(row) > cols for row in values):
            raise ValueError(f"values do not fit in {normalized}")
        response = _mapping(
            self._service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=normalized,
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute(),
            "update",
        )
        return {
            "spreadsheetId": sheet_id,
            "updatedRange": response.get("updatedRange") or normalized,
            "updatedRows": response.get("updatedRows"),
            "updatedCells": response.get("updatedCells"),
        }

    def append(self, spreadsheet_id: str, range_name: str, values: list[list[Any]]) -> dict[str, object]:
        sheet_id = self._require_allowed(spreadsheet_id)
        normalized = append_sheet_range(range_name)
        if len(values) > self._max_read_rows or sum(len(row) for row in values) > self._max_write_cells:
            raise ValueError("append values exceed the configured cell limit")
        response = _mapping(
            self._service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=normalized,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            ).execute(),
            "append",
        )
        updates = response.get("updates")
        updated = cast(dict[str, object], updates) if isinstance(updates, dict) else {}
        return {
            "spreadsheetId": sheet_id,
            "updatedRange": updated.get("updatedRange"),
            "updatedRows": updated.get("updatedRows"),
            "updatedCells": updated.get("updatedCells"),
        }

    def _check_box(self, rows: int, cols: int) -> None:
        if rows > self._max_read_rows or rows * cols > self._max_write_cells:
            raise ValueError(
                f"range is larger than {self._max_read_rows} rows or {self._max_write_cells} cells"
            )


def build_sheets_client(sheets: SheetsToolConfig, drive: DriveToolConfig) -> _SheetsClient:
    deps = _require_google_deps()
    creds_path = resolve_sheets_credentials_path(sheets, drive)
    allowed = frozenset(item.strip() for item in sheets.spreadsheet_ids if item.strip())
    if not allowed:
        raise ValueError("spreadsheet_ids must list at least one spreadsheet ID")
    service = build_google_service(
        deps,
        "sheets",
        "v4",
        credentials_path=creds_path,
        scope=_SHEETS_SCOPE,
        timeout=_SHEETS_HTTP_TIMEOUT_SECONDS,
    )
    return _SheetsClient(
        cast(_SheetsService, service),
        allowed,
        max_read_rows=sheets.max_read_rows,
        max_write_cells=sheets.max_write_cells,
    )


def _selected_spreadsheet(configured: list[str], spreadsheet_id: str | None) -> str:
    selected = (spreadsheet_id or "").strip()
    if selected:
        return selected
    if len(configured) == 1:
        return configured[0]
    raise ValueError("spreadsheet_id is required when more than one spreadsheet is configured")


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "Sheets action",
            enum=["list", "read", "update", "append"],
        ),
        spreadsheet_id=StringSchema(
            "Spreadsheet ID from the sheet URL. Omit when only one spreadsheet is configured.",
            nullable=True,
        ),
        range=StringSchema(
            "A1 range. read and update require a bounded range such as Sheet1!A1:C20. "
            "append accepts Sheet1!A1 or Sheet1!A:C.",
            nullable=True,
        ),
        values_json=StringSchema(
            "JSON array of rows for update or append, for example "
            '[["Name","Amount"],["Rent",1200]]. Numbers and booleans stay typed. '
            "USER_ENTERED input also accepts formulas.",
            nullable=True,
        ),
        required=["action"],
    )
)
class GoogleSheetsTool(Tool):
    """Read and update Google Sheets shared with a service account."""

    config_key = "sheets"

    @classmethod
    def config_cls(cls):
        return SheetsToolConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        sheets = ctx.config.sheets
        if not sheets.enabled or not any(item.strip() for item in sheets.spreadsheet_ids):
            return False
        if sheets_service_account_email(sheets, ctx.config.drive) is None:
            return False
        try:
            _require_google_deps()
        except RuntimeError:
            return False
        return True

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(sheets=ctx.config.sheets, drive=ctx.config.drive)

    def __init__(self, *, sheets: SheetsToolConfig, drive: DriveToolConfig) -> None:
        self._sheets = sheets
        self._drive = drive
        self._client: _SheetsClient | None = None

    def _get_client(self) -> _SheetsClient:
        if self._client is None:
            self._client = build_sheets_client(self._sheets, self._drive)
        return self._client

    @property
    def name(self) -> str:
        return "google_sheets"

    @property
    def description(self) -> str:
        return (
            "Read and update Google Sheets shared with the configured service account. "
            "Use list to see tab names, read a bounded A1 range, then update or append rows. "
            "Only configured spreadsheet IDs are allowed."
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = super().validate_params(params)
        action = params.get("action")
        if action in {"read", "update", "append"} and not str(params.get("range") or "").strip():
            errors.append(f"range is required when action='{action}'")
        if action in {"update", "append"} and not str(params.get("values_json") or "").strip():
            errors.append(f"values_json is required when action='{action}'")
        return errors

    async def execute(self, **kwargs: Any) -> Any:
        action = str(kwargs.get("action") or "")
        spreadsheet_id = kwargs.get("spreadsheet_id")
        range_name = kwargs.get("range")
        values_json = kwargs.get("values_json")
        spreadsheet = spreadsheet_id if isinstance(spreadsheet_id, str) else None
        cell_range = range_name if isinstance(range_name, str) else None
        raw_values = values_json if isinstance(values_json, str) else None
        try:
            client = self._get_client()
        except (RuntimeError, ValueError) as exc:
            return ToolResult.error(f"Error: {exc}")

        try:
            if action == "list":
                items = await asyncio.to_thread(client.list_configured)
                return json.dumps({"spreadsheets": items}, indent=2)
            selected = _selected_spreadsheet(self._sheets.spreadsheet_ids, spreadsheet)
            if action == "read":
                payload = await asyncio.to_thread(client.read, selected, str(cell_range or ""))
                return json.dumps(payload, indent=2)
            if action not in {"update", "append"}:
                return ToolResult.error(f"Error: unknown action '{action}'")
            values = parse_sheet_values(
                str(raw_values or ""),
                max_rows=self._sheets.max_read_rows,
                max_cells=self._sheets.max_write_cells,
            )
            if action == "update":
                payload = await asyncio.to_thread(client.update, selected, str(cell_range or ""), values)
                return json.dumps(payload, indent=2)
            payload = await asyncio.to_thread(client.append, selected, str(cell_range or ""), values)
            return json.dumps(payload, indent=2)
        except (PermissionError, ValueError) as exc:
            return ToolResult.error(f"Error: {exc}")
        except Exception as exc:
            return ToolResult.error(f"Error: Sheets API request failed: {exc}")
