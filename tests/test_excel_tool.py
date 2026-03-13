"""Tests for spreadsheet tools (ReadSpreadsheetTool, QueryDataTool, DescribeDataTool)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.excel import (
    DescribeDataTool,
    QueryDataTool,
    ReadExcelTool,
    ReadSpreadsheetTool,
    _validate_select_only,
)
from nanobot.agent.tools.result_cache import ToolResultCache

openpyxl = pytest.importorskip("openpyxl")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_workbook(tmp_path: Path) -> Path:
    """Create a small .xlsx workbook for testing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tasks"
    ws.append(["Line #", "Name", "Status", "Start", "Finish"])
    ws.append([1, "Project Alpha", "Open/Active", "2026-03-01", "2026-06-30"])
    ws.append([2, "Design Phase", "Completed", "2026-03-01", "2026-03-15"])
    ws.append([3, "Build Phase", "Open/Active", "2026-03-16", "2026-05-31"])
    ws.append([None, None, None, None, None])  # empty row
    ws.append([4, "Testing", "Not Started", "2026-06-01", "2026-06-30"])

    ws2 = wb.create_sheet("Resources")
    ws2.append(["Name", "Role", "Utilization"])
    ws2.append(["Alice", "PM", 0.8])
    ws2.append(["Bob", "Dev", 1.0])

    path = tmp_path / "plan.xlsx"
    wb.save(path)
    wb.close()
    return path


@pytest.fixture()
def cache(tmp_path: Path) -> ToolResultCache:
    return ToolResultCache(workspace=tmp_path)


@pytest.fixture()
def tool(tmp_path: Path, cache: ToolResultCache) -> ReadSpreadsheetTool:
    return ReadSpreadsheetTool(workspace=tmp_path, cache=cache)


def _make_per_sheet_cache(rows: list[dict]) -> MagicMock:
    """Create a mock ToolResultCache with per-sheet cache format."""
    full_output = json.dumps(
        {
            "headers": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "row_count": len(rows),
            "total_rows": len(rows),
        }
    )
    entry = MagicMock()
    entry.full_output = full_output
    cache = MagicMock()
    cache.get.return_value = entry
    return cache


# ---------------------------------------------------------------------------
# ReadSpreadsheetTool — Excel tests (existing)
# ---------------------------------------------------------------------------


async def test_read_all_sheets(tool: ReadSpreadsheetTool, sample_workbook: Path) -> None:
    result = await tool.execute(path=str(sample_workbook))
    assert result.success
    data = json.loads(result.output)
    assert "Tasks" in data["sheets"]
    assert "Resources" in data["sheets"]
    # Metadata should contain cache_key, headers, row_count — but no rows
    tasks = data["sheets"]["Tasks"]
    assert tasks["row_count"] == 4  # rows 1-4 (empty row skipped)
    assert "cache_key" in tasks
    assert "rows" not in tasks  # rows are in cache, not in output


async def test_read_specific_sheet(
    tool: ReadSpreadsheetTool,
    sample_workbook: Path,
    cache: ToolResultCache,
) -> None:
    result = await tool.execute(path=str(sample_workbook), sheet="Resources")
    assert result.success
    data = json.loads(result.output)
    assert "Resources" in data["sheets"]
    assert "Tasks" not in data["sheets"]
    meta = data["sheets"]["Resources"]
    assert meta["row_count"] == 2
    assert "cache_key" in meta
    # Verify actual rows are in the cache
    entry = cache.get(meta["cache_key"])
    assert entry is not None
    cached = json.loads(entry.full_output)
    assert len(cached["rows"]) == 2
    assert cached["rows"][0]["Name"] == "Alice"
    assert cached["rows"][1]["Utilization"] == 1.0


async def test_column_filter(
    tool: ReadSpreadsheetTool,
    sample_workbook: Path,
    cache: ToolResultCache,
) -> None:
    result = await tool.execute(
        path=str(sample_workbook), sheet="Tasks", columns=["Name", "Status"]
    )
    assert result.success
    data = json.loads(result.output)
    meta = data["sheets"]["Tasks"]
    assert set(meta["headers"]) == {"Name", "Status"}
    # Verify cached rows only have filtered columns
    entry = cache.get(meta["cache_key"])
    cached = json.loads(entry.full_output)
    assert set(cached["rows"][0].keys()) == {"Name", "Status"}


async def test_max_rows(tool: ReadSpreadsheetTool, sample_workbook: Path) -> None:
    result = await tool.execute(path=str(sample_workbook), sheet="Tasks", max_rows=2)
    assert result.success
    data = json.loads(result.output)
    sheet = data["sheets"]["Tasks"]
    assert sheet["row_count"] == 2
    assert sheet["truncated"] is True


async def test_missing_sheet(tool: ReadSpreadsheetTool, sample_workbook: Path) -> None:
    result = await tool.execute(path=str(sample_workbook), sheet="Nonexistent")
    assert not result.success
    assert "not found" in result.output.lower()


async def test_file_not_found(tool: ReadSpreadsheetTool, tmp_path: Path) -> None:
    result = await tool.execute(path=str(tmp_path / "nope.xlsx"))
    assert not result.success
    assert "not found" in result.output.lower()


async def test_unsupported_extension(tool: ReadSpreadsheetTool, tmp_path: Path) -> None:
    txt = tmp_path / "data.json"
    txt.write_text('{"a": 1}')
    result = await tool.execute(path=str(txt))
    assert not result.success
    assert "unsupported" in result.output.lower()


async def test_path_traversal_blocked(tmp_path: Path, sample_workbook: Path) -> None:
    """Tool with allowed_dir should block paths outside the workspace."""
    restricted = ReadSpreadsheetTool(workspace=tmp_path, allowed_dir=tmp_path / "safe")
    (tmp_path / "safe").mkdir()
    result = await restricted.execute(path=str(sample_workbook))
    assert not result.success
    assert "outside" in result.output.lower()


async def test_backward_compat_alias() -> None:
    """ReadExcelTool alias still works."""
    assert ReadExcelTool is ReadSpreadsheetTool


# ---------------------------------------------------------------------------
# ReadSpreadsheetTool — CSV tests
# ---------------------------------------------------------------------------


async def test_read_csv_basic(
    tool: ReadSpreadsheetTool,
    tmp_path: Path,
    cache: ToolResultCache,
) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("Name,Amount,Status\nAlice,100,active\nBob,200,inactive\n")
    result = await tool.execute(path=str(csv_file))
    assert result.success
    data = json.loads(result.output)
    meta = data["sheets"]["data"]
    assert meta["headers"] == ["Name", "Amount", "Status"]
    assert meta["row_count"] == 2
    assert "cache_key" in meta
    # Verify actual rows in cache
    entry = cache.get(meta["cache_key"])
    cached = json.loads(entry.full_output)
    assert cached["rows"][0]["Name"] == "Alice"
    assert cached["rows"][0]["Amount"] == 100  # coerced to int
    assert cached["rows"][1]["Amount"] == 200


async def test_read_csv_semicolon_delimited(
    tool: ReadSpreadsheetTool,
    tmp_path: Path,
    cache: ToolResultCache,
) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("Name;Amount;Status\nAlice;100;active\nBob;200;inactive\n")
    result = await tool.execute(path=str(csv_file))
    assert result.success
    data = json.loads(result.output)
    meta = data["sheets"]["data"]
    assert meta["row_count"] == 2
    entry = cache.get(meta["cache_key"])
    cached = json.loads(entry.full_output)
    assert cached["rows"][0]["Name"] == "Alice"


async def test_read_csv_with_bom(
    tool: ReadSpreadsheetTool,
    tmp_path: Path,
    cache: ToolResultCache,
) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_bytes(b"\xef\xbb\xbfName,Value\nA,1\nB,2\n")
    result = await tool.execute(path=str(csv_file))
    assert result.success
    data = json.loads(result.output)
    meta = data["sheets"]["data"]
    assert meta["headers"] == ["Name", "Value"]
    entry = cache.get(meta["cache_key"])
    cached = json.loads(entry.full_output)
    assert cached["rows"][0]["Name"] == "A"


async def test_read_csv_empty_rows_skipped(tool: ReadSpreadsheetTool, tmp_path: Path) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("A,B\n1,2\n,,\n3,4\n")
    result = await tool.execute(path=str(csv_file))
    assert result.success
    data = json.loads(result.output)
    sheet = data["sheets"]["data"]
    assert sheet["row_count"] == 2  # empty row skipped


# ---------------------------------------------------------------------------
# Large-dataset hint
# ---------------------------------------------------------------------------


async def test_large_dataset_hint(tool: ReadSpreadsheetTool, tmp_path: Path) -> None:
    """Sheets with >50 rows should include a hint about query_data."""
    csv_file = tmp_path / "big.csv"
    lines = ["id,value"] + [f"{i},{i * 10}" for i in range(60)]
    csv_file.write_text("\n".join(lines))
    result = await tool.execute(path=str(csv_file))
    assert result.success
    data = json.loads(result.output)
    sheet = data["sheets"]["big"]
    assert "hint" in sheet
    assert "query_data" in sheet["hint"]


async def test_small_dataset_no_hint(tool: ReadSpreadsheetTool, tmp_path: Path) -> None:
    csv_file = tmp_path / "small.csv"
    csv_file.write_text("a,b\n1,2\n3,4\n")
    result = await tool.execute(path=str(csv_file))
    assert result.success
    data = json.loads(result.output)
    sheet = data["sheets"]["small"]
    assert "hint" not in sheet


# ---------------------------------------------------------------------------
# SQL safety validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql,expected_ok",
    [
        ("SELECT * FROM data", True),
        ("  select count(*) from data  ", True),
        ("WITH cte AS (SELECT 1) SELECT * FROM cte", True),
        ("INSERT INTO data VALUES (1)", False),
        ("DROP TABLE data", False),
        ("DELETE FROM data", False),
        ("UPDATE data SET x = 1", False),
        ("SELECT 1; DROP TABLE data", False),
        ("CREATE TABLE evil (x INT)", False),
        ("ALTER TABLE data ADD COLUMN y INT", False),
        ("TRUNCATE TABLE data", False),
        ("-- comment\nSELECT 1", True),
        ("/* block */SELECT 1", True),
        ("", False),
    ],
)
def test_validate_select_only(sql: str, expected_ok: bool) -> None:
    result = _validate_select_only(sql)
    if expected_ok:
        assert result is None, f"Expected OK for: {sql!r}, got: {result}"
    else:
        assert result is not None, f"Expected rejection for: {sql!r}"


# ---------------------------------------------------------------------------
# QueryDataTool tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_cache() -> MagicMock:
    return _make_per_sheet_cache(
        [
            {"Name": "Alice", "Department": "Engineering", "Salary": 100000},
            {"Name": "Bob", "Department": "Engineering", "Salary": 120000},
            {"Name": "Carol", "Department": "Marketing", "Salary": 90000},
            {"Name": "Dave", "Department": "Marketing", "Salary": 95000},
        ]
    )


async def test_query_data_basic_select(sample_cache: MagicMock) -> None:
    tool = QueryDataTool(cache=sample_cache)
    result = await tool.execute(cache_key="abc123", query="SELECT * FROM data")
    assert result.success
    data = json.loads(result.output)
    assert data["row_count"] == 4
    assert "Name" in data["columns"]


async def test_query_data_where_filter(sample_cache: MagicMock) -> None:
    tool = QueryDataTool(cache=sample_cache)
    result = await tool.execute(
        cache_key="abc123",
        query="SELECT Name FROM data WHERE Department = 'Engineering'",
    )
    assert result.success
    data = json.loads(result.output)
    assert data["row_count"] == 2
    names = {r["Name"] for r in data["rows"]}
    assert names == {"Alice", "Bob"}


async def test_query_data_aggregation(sample_cache: MagicMock) -> None:
    tool = QueryDataTool(cache=sample_cache)
    result = await tool.execute(
        cache_key="abc123",
        query="SELECT Department, SUM(Salary) as total FROM data GROUP BY Department",
    )
    assert result.success
    data = json.loads(result.output)
    assert data["row_count"] == 2
    totals = {r["Department"]: r["total"] for r in data["rows"]}
    assert totals["Engineering"] == 220000
    assert totals["Marketing"] == 185000


async def test_query_data_rejects_non_select(sample_cache: MagicMock) -> None:
    tool = QueryDataTool(cache=sample_cache)
    result = await tool.execute(cache_key="abc123", query="DROP TABLE data")
    assert not result.success
    assert "only select" in result.output.lower()


async def test_query_data_invalid_sql(sample_cache: MagicMock) -> None:
    tool = QueryDataTool(cache=sample_cache)
    result = await tool.execute(cache_key="abc123", query="SELECT nonexistent FROM data")
    assert not result.success
    assert "sql error" in result.output.lower() or "error" in result.output.lower()


async def test_query_data_missing_cache_key() -> None:
    cache = MagicMock()
    cache.get.return_value = None
    tool = QueryDataTool(cache=cache)
    result = await tool.execute(cache_key="missing", query="SELECT * FROM data")
    assert not result.success
    assert "no cached result" in result.output.lower()


async def test_query_data_missing_sheet(sample_cache: MagicMock) -> None:
    """With per-sheet cache format, sheet param is ignored (key already has one sheet)."""
    tool = QueryDataTool(cache=sample_cache)
    result = await tool.execute(cache_key="abc123", query="SELECT * FROM data", sheet="Nonexistent")
    # Per-sheet format ignores the sheet param — the entry IS the sheet
    assert result.success


# ---------------------------------------------------------------------------
# DescribeDataTool tests
# ---------------------------------------------------------------------------


async def test_describe_data_columns(sample_cache: MagicMock) -> None:
    tool = DescribeDataTool(cache=sample_cache)
    result = await tool.execute(cache_key="abc123")
    assert result.success
    data = json.loads(result.output)
    assert data["row_count"] == 4
    col_names = [c["name"] for c in data["columns"]]
    assert "Name" in col_names
    assert "Salary" in col_names


async def test_describe_data_stats(sample_cache: MagicMock) -> None:
    tool = DescribeDataTool(cache=sample_cache)
    result = await tool.execute(cache_key="abc123")
    assert result.success
    data = json.loads(result.output)
    salary_col = next(c for c in data["columns"] if c["name"] == "Salary")
    assert salary_col["non_null"] == 4
    assert salary_col["min"] == 90000
    assert salary_col["max"] == 120000


async def test_describe_data_sample_rows(sample_cache: MagicMock) -> None:
    tool = DescribeDataTool(cache=sample_cache)
    result = await tool.execute(cache_key="abc123")
    assert result.success
    data = json.loads(result.output)
    assert len(data["sample_rows"]) == 4  # only 4 rows total, all returned


async def test_describe_data_missing_cache_key() -> None:
    cache = MagicMock()
    cache.get.return_value = None
    tool = DescribeDataTool(cache=cache)
    result = await tool.execute(cache_key="missing")
    assert not result.success
    assert "no cached result" in result.output.lower()
