"""Tests for ReadExcelTool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.tools.excel import ReadExcelTool

openpyxl = pytest.importorskip("openpyxl")


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
def tool(tmp_path: Path) -> ReadExcelTool:
    return ReadExcelTool(workspace=tmp_path)


async def test_read_all_sheets(tool: ReadExcelTool, sample_workbook: Path) -> None:
    result = await tool.execute(path=str(sample_workbook))
    assert result.success
    data = json.loads(result.output)
    assert "Tasks" in data["sheets"]
    assert "Resources" in data["sheets"]
    # Empty row should be skipped
    tasks = data["sheets"]["Tasks"]
    assert tasks["row_count"] == 4  # rows 1-4 (empty row skipped)


async def test_read_specific_sheet(tool: ReadExcelTool, sample_workbook: Path) -> None:
    result = await tool.execute(path=str(sample_workbook), sheet="Resources")
    assert result.success
    data = json.loads(result.output)
    assert "Resources" in data["sheets"]
    assert "Tasks" not in data["sheets"]
    rows = data["sheets"]["Resources"]["rows"]
    assert len(rows) == 2
    assert rows[0]["Name"] == "Alice"
    assert rows[1]["Utilization"] == 1.0


async def test_column_filter(tool: ReadExcelTool, sample_workbook: Path) -> None:
    result = await tool.execute(
        path=str(sample_workbook), sheet="Tasks", columns=["Name", "Status"]
    )
    assert result.success
    data = json.loads(result.output)
    rows = data["sheets"]["Tasks"]["rows"]
    assert set(rows[0].keys()) == {"Name", "Status"}


async def test_max_rows(tool: ReadExcelTool, sample_workbook: Path) -> None:
    result = await tool.execute(path=str(sample_workbook), sheet="Tasks", max_rows=2)
    assert result.success
    data = json.loads(result.output)
    sheet = data["sheets"]["Tasks"]
    assert sheet["row_count"] == 2
    assert sheet["truncated"] is True


async def test_missing_sheet(tool: ReadExcelTool, sample_workbook: Path) -> None:
    result = await tool.execute(path=str(sample_workbook), sheet="Nonexistent")
    assert not result.success
    assert "not found" in result.output.lower()


async def test_file_not_found(tool: ReadExcelTool, tmp_path: Path) -> None:
    result = await tool.execute(path=str(tmp_path / "nope.xlsx"))
    assert not result.success
    assert "not found" in result.output.lower()


async def test_unsupported_extension(tool: ReadExcelTool, tmp_path: Path) -> None:
    txt = tmp_path / "data.csv"
    txt.write_text("a,b\n1,2\n")
    result = await tool.execute(path=str(txt))
    assert not result.success
    assert "unsupported" in result.output.lower()


async def test_path_traversal_blocked(tmp_path: Path, sample_workbook: Path) -> None:
    """Tool with allowed_dir should block paths outside the workspace."""
    restricted = ReadExcelTool(workspace=tmp_path, allowed_dir=tmp_path / "safe")
    (tmp_path / "safe").mkdir()
    result = await restricted.execute(path=str(sample_workbook))
    assert not result.success
    assert "outside" in result.output.lower()
