"""Excel file reader tool."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.filesystem import _resolve_path

if TYPE_CHECKING:
    from nanobot.agent.tools.result_cache import ToolResultCache

# Pattern for repeating date-allocation columns like "3/1/2026 (d)"
_DATE_ALLOC_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}\s*\(")


class ReadExcelTool(Tool):
    """Read an Excel workbook and return structured sheet data.

    Returns sheet names and row data as JSON so the agent can analyse
    spreadsheets without shelling out to Python.  Only the first
    ``max_rows`` rows per sheet are returned to stay within token limits.
    """

    readonly = True

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        max_rows: int = 200,
    ):
        self._workspace = workspace
        self._allowed_dir = allowed_dir
        self._max_rows = max_rows

    @property
    def name(self) -> str:
        return "read_excel"

    @property
    def description(self) -> str:
        return (
            "Read an Excel (.xlsx/.xls) workbook and return sheet names, headers, "
            "and row data as JSON. Use this instead of exec for spreadsheet analysis."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the Excel file (.xlsx or .xls)",
                },
                "sheet": {
                    "type": "string",
                    "description": ("Sheet name to read. If omitted, reads all sheets."),
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum rows to return per sheet (default 200)",
                    "minimum": 1,
                    "maximum": 5000,
                },
                "columns": {
                    "type": "array",
                    "description": (
                        "Column names to include. If omitted, all columns are returned."
                    ),
                    "items": {"type": "string"},
                },
            },
            "required": ["path"],
        }

    async def execute(  # type: ignore[override]
        self,
        path: str,
        sheet: str | None = None,
        max_rows: int | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            import openpyxl
        except ImportError:
            return ToolResult.fail(
                "openpyxl is not installed. Run: pip install openpyxl",
                error_type="missing_dependency",
            )

        try:
            file_path = _resolve_path(str(path), self._workspace, self._allowed_dir)
        except PermissionError as exc:
            return ToolResult.fail(f"Error: {exc}")

        if not file_path.exists():
            return ToolResult.fail(f"Error: File not found: {path}")
        if not file_path.is_file():
            return ToolResult.fail(f"Error: Not a file: {path}")

        suffix = file_path.suffix.lower()
        if suffix not in (".xlsx", ".xls", ".xlsm", ".xlsb"):
            return ToolResult.fail(f"Error: Unsupported file type: {suffix}")

        cap = max_rows or self._max_rows

        try:
            wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
        except Exception as exc:
            return ToolResult.fail(f"Error opening workbook: {exc}")

        try:
            sheet_names = wb.sheetnames
            target_sheets = [sheet] if sheet else sheet_names

            if sheet and sheet not in sheet_names:
                wb.close()
                return ToolResult.fail(
                    f"Sheet '{sheet}' not found. Available: {', '.join(sheet_names)}"
                )

            result: dict[str, Any] = {"file": str(file_path.name), "sheets": {}}

            for sname in target_sheets:
                ws = wb[sname]
                rows_iter = ws.iter_rows(values_only=True)

                # First row = headers
                header_row = next(rows_iter, None)
                if header_row is None:
                    result["sheets"][sname] = {"headers": [], "rows": [], "total_rows": 0}
                    continue

                headers = [
                    str(h) if h is not None else f"col_{i}" for i, h in enumerate(header_row)
                ]

                # Determine column indices to keep
                if columns:
                    col_set = set(columns)
                    keep_idx = [i for i, h in enumerate(headers) if h in col_set]
                    if not keep_idx:
                        result["sheets"][sname] = {
                            "headers": headers,
                            "rows": [],
                            "total_rows": 0,
                            "note": f"None of {columns} matched headers",
                        }
                        continue
                    headers = [headers[i] for i in keep_idx]
                else:
                    keep_idx = list(range(len(headers)))

                # Read all rows (up to cap) first
                raw_rows: list[list[Any]] = []
                total = 0
                for row in rows_iter:
                    total += 1
                    if total <= cap:
                        vals = [row[i] if i < len(row) else None for i in keep_idx]
                        raw_rows.append(vals)

                # Auto-strip columns that are entirely empty when user
                # did not request specific columns — avoids bloat from
                # hundreds of sparse date-allocation columns.
                stripped_count = 0
                if not columns and raw_rows:
                    non_empty = set()
                    for vals in raw_rows:
                        for ci, v in enumerate(vals):
                            if v is not None and not (isinstance(v, str) and not v.strip()):
                                non_empty.add(ci)
                    if len(non_empty) < len(headers):
                        stripped_count = len(headers) - len(non_empty)
                        ordered = sorted(non_empty)
                        headers = [headers[ci] for ci in ordered]
                        raw_rows = [[vals[ci] for ci in ordered] for vals in raw_rows]

                # Separate date-allocation columns from metadata columns.
                # Date-alloc columns (e.g. "3/1/2026 (d)") are collapsed into a
                # compact per-row summary to avoid massive JSON bloat.
                meta_idx: list[int] = []
                alloc_idx: list[int] = []
                for ci, h in enumerate(headers):
                    if _DATE_ALLOC_RE.match(h):
                        alloc_idx.append(ci)
                    else:
                        meta_idx.append(ci)

                # Build row dicts, skipping empty rows and omitting null values
                data_rows: list[dict[str, Any]] = []
                for vals in raw_rows:
                    if all(v is None or (isinstance(v, str) and not v.strip()) for v in vals):
                        continue
                    record: dict[str, Any] = {}
                    for ci in meta_idx:
                        sv = _serialize(vals[ci])
                        if sv is not None:
                            record[headers[ci]] = sv
                    # Collapse date-allocation columns into a compact summary
                    if alloc_idx:
                        alloc_summary = _summarize_allocations(
                            [(headers[ci], vals[ci]) for ci in alloc_idx]
                        )
                        if alloc_summary:
                            record["_allocations"] = alloc_summary
                    if record:
                        data_rows.append(record)

                meta_headers = [headers[ci] for ci in meta_idx]
                sheet_data: dict[str, Any] = {
                    "headers": meta_headers,
                    "row_count": len(data_rows),
                    "total_rows": total,
                    "rows": data_rows,
                }
                if total > cap:
                    sheet_data["truncated"] = True
                    sheet_data["note"] = f"Showing first {cap} of {total} rows"
                if stripped_count:
                    sheet_data["empty_columns_removed"] = stripped_count
                if alloc_idx:
                    sheet_data["date_columns_collapsed"] = len(alloc_idx)
                result["sheets"][sname] = sheet_data

            wb.close()
        except Exception as exc:
            wb.close()
            return ToolResult.fail(f"Error reading workbook: {exc}")

        output = json.dumps(result, ensure_ascii=False, default=str)
        truncated = len(output) > 200_000
        if truncated:
            output = output[:200_000] + "\n... (output truncated)"
        return ToolResult.ok(output, truncated=truncated)


def _serialize(val: Any) -> Any:
    """Convert cell value to a JSON-friendly type."""
    if val is None:
        return None
    # datetime objects → ISO string
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _summarize_allocations(pairs: list[tuple[str, Any]]) -> str | None:
    """Collapse date-allocation column values into a compact summary.

    Given pairs of (header, value) for date columns like "3/1/2026 (d)",
    returns a string like "3/3/2026..12/4/2026 total=350.0 avg=2.0/day"
    or None if no non-null values exist.
    """
    non_null = [(h, v) for h, v in pairs if v is not None and v != 0]
    if not non_null:
        return None
    first_date = non_null[0][0].split("(")[0].strip()
    last_date = non_null[-1][0].split("(")[0].strip()
    total = sum(float(v) for _, v in non_null if isinstance(v, (int, float)))
    days = len(non_null)
    avg = round(total / days, 2) if days else 0
    return f"{first_date}..{last_date} days={days} total={total} avg={avg}/day"


# ---------------------------------------------------------------------------
# Cache-backed retrieval tools
# ---------------------------------------------------------------------------


class ExcelGetRowsTool(Tool):
    """Retrieve a row range from a previously cached Excel result."""

    readonly = True
    cacheable = False

    def __init__(self, cache: ToolResultCache) -> None:
        self._cache = cache

    @property
    def name(self) -> str:
        return "excel_get_rows"

    @property
    def description(self) -> str:
        return (
            "Retrieve a range of rows from a previously cached read_excel result. "
            "Use the cache_key from the read_excel summary."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cache_key": {
                    "type": "string",
                    "description": "The cache key from a prior read_excel call.",
                },
                "sheet": {
                    "type": "string",
                    "description": "Sheet name. If omitted, returns rows from the first sheet.",
                },
                "start_row": {
                    "type": "integer",
                    "description": "Start row index (0-based). Default 0.",
                    "minimum": 0,
                },
                "end_row": {
                    "type": "integer",
                    "description": "End row index (exclusive). Default 25.",
                    "minimum": 1,
                },
            },
            "required": ["cache_key"],
        }

    async def execute(  # type: ignore[override]
        self,
        cache_key: str,
        sheet: str | None = None,
        start_row: int = 0,
        end_row: int = 25,
        **kwargs: Any,
    ) -> ToolResult:
        entry = self._cache.get(cache_key)
        if entry is None:
            return ToolResult.fail(
                f"No cached result for key '{cache_key}'.", error_type="not_found"
            )

        try:
            parsed = json.loads(entry.full_output)
        except (json.JSONDecodeError, TypeError):
            return ToolResult.fail("Cached result is not valid JSON.", error_type="parse_error")

        sheets = parsed.get("sheets", {})
        if not sheets:
            return ToolResult.fail("No sheets found in cached result.", error_type="not_found")

        if sheet:
            sheet_data = sheets.get(sheet)
            if not sheet_data:
                available = list(sheets.keys())
                return ToolResult.fail(
                    f"Sheet '{sheet}' not found. Available: {available}",
                    error_type="not_found",
                )
        else:
            sheet_data = next(iter(sheets.values()))

        rows = sheet_data.get("rows", [])
        sliced = rows[start_row:end_row]
        total = len(rows)
        output = json.dumps(
            {"rows": sliced, "range": f"{start_row}-{min(end_row, total)}", "total_rows": total},
            ensure_ascii=False,
            default=str,
        )
        return ToolResult.ok(output)


class ExcelFindTool(Tool):
    """Search cached Excel data for matching rows."""

    readonly = True
    cacheable = False

    def __init__(self, cache: ToolResultCache) -> None:
        self._cache = cache

    @property
    def name(self) -> str:
        return "excel_find"

    @property
    def description(self) -> str:
        return (
            "Search a cached read_excel result for rows matching a text query. "
            "Searches all columns or a specific column."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cache_key": {
                    "type": "string",
                    "description": "The cache key from a prior read_excel call.",
                },
                "query": {
                    "type": "string",
                    "description": "Text to search for (case-insensitive substring match).",
                },
                "column": {
                    "type": "string",
                    "description": "Column name to limit search to. If omitted, searches all.",
                },
                "sheet": {
                    "type": "string",
                    "description": "Sheet name. If omitted, searches the first sheet.",
                },
            },
            "required": ["cache_key", "query"],
        }

    async def execute(  # type: ignore[override]
        self,
        cache_key: str,
        query: str,
        column: str | None = None,
        sheet: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        entry = self._cache.get(cache_key)
        if entry is None:
            return ToolResult.fail(
                f"No cached result for key '{cache_key}'.", error_type="not_found"
            )

        try:
            parsed = json.loads(entry.full_output)
        except (json.JSONDecodeError, TypeError):
            return ToolResult.fail("Cached result is not valid JSON.", error_type="parse_error")

        sheets = parsed.get("sheets", {})
        if not sheets:
            return ToolResult.fail("No sheets found in cached result.", error_type="not_found")

        if sheet:
            sheet_data = sheets.get(sheet)
            if not sheet_data:
                return ToolResult.fail(f"Sheet '{sheet}' not found.", error_type="not_found")
        else:
            sheet_data = next(iter(sheets.values()))

        rows = sheet_data.get("rows", [])
        q = query.lower()
        matches: list[dict[str, Any]] = []

        for row in rows:
            if column:
                val = row.get(column, "")
                if q in str(val).lower():
                    matches.append(row)
            else:
                if any(q in str(v).lower() for v in row.values()):
                    matches.append(row)

        output = json.dumps(
            {"query": query, "matches": len(matches), "rows": matches[:50]},
            ensure_ascii=False,
            default=str,
        )
        return ToolResult.ok(output)
