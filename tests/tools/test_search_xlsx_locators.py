"""Spreadsheet grep locators follow cells, including literal tabs in cell values."""

from pathlib import Path

import pytest
from openpyxl import Workbook

from nanobot.agent.tools.search import GrepTool


@pytest.mark.parametrize(
    ("cells", "expected_cell"),
    [
        (["left\ttab", "needle"], "B1"),
        (["before\tneedle", "other"], "A1"),
        ([None, "left\ttab", None, "needle"], "D1"),
        ([None, "needle"], "B1"),
        (["left", "needle"], "B1"),
    ],
    ids=["tab-in-earlier-cell", "match-after-tab-in-cell", "tab-and-empty-cells", "empty-leading-cell", "plain-cells"],
)
@pytest.mark.asyncio
async def test_grep_xlsx_literal_tabs_keep_source_cell(
    tmp_path: Path, cells: list[str | None], expected_cell: str,
) -> None:
    workbook = Workbook()
    workbook.active.title = "Data"
    workbook.active.append(cells)
    workbook.save(tmp_path / "data.xlsx")
    workbook.close()

    result = await GrepTool(workspace=tmp_path, allowed_dir=tmp_path).execute(
        pattern="needle", path="data.xlsx", fixed_strings=True, output_mode="content",
    )

    assert f"sheet='Data',row=1,cell={expected_cell}" in result
    # Metadata must not escape or otherwise change the original extracted text.
    extracted = "\t".join(cell if cell is not None else "" for cell in cells)
    assert f"> 2 [sheet='Data',row=1]| {extracted}" in result
