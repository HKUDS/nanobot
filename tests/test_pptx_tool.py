"""Tests for the PowerPoint reader and analysis tools."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TOOLS_PATH = Path.home() / ".nanobot" / "workspace" / "skills" / "powerpoint" / "tools.py"


def _load_tools_module():
    """Load the powerpoint tools module from the workspace skill path."""
    spec = importlib.util.spec_from_file_location("pptx_tools", str(TOOLS_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pptx_tools"] = mod
    spec.loader.exec_module(mod)
    return mod


# Skip the entire module if the tools.py file doesn't exist
pytestmark = pytest.mark.skipif(not TOOLS_PATH.exists(), reason="powerpoint skill not installed")


@pytest.fixture(scope="module")
def pptx_mod():
    return _load_tools_module()


@pytest.fixture
def tool(pptx_mod):
    return pptx_mod.ReadPptxTool()


@pytest.fixture
def analyze_tool(pptx_mod):
    return pptx_mod.AnalyzePptxTool()


# ---------------------------------------------------------------------------
# Helper: mock presentation builder
# ---------------------------------------------------------------------------


def _make_mock_presentation(slides_data: list[dict[str, Any]]) -> MagicMock:
    """Create a mock pptx.Presentation with the given slide data."""
    mock_slides = []
    for slide_data in slides_data:
        slide = MagicMock()

        shapes = []
        for text in slide_data.get("texts", []):
            shape = MagicMock()
            shape.text = text
            shape.has_table = False
            type(shape).__name__ = "Shape"
            shapes.append(shape)

        for table_rows in slide_data.get("tables", []):
            shape = MagicMock()
            shape.text = ""
            shape.has_table = True
            type(shape).__name__ = "Table"
            rows = []
            for row_cells in table_rows:
                row = MagicMock()
                cells = [MagicMock(text=ct) for ct in row_cells]
                row.cells = cells
                rows.append(row)
            shape.table.rows = rows
            shapes.append(shape)

        slide.shapes = shapes

        if slide_data.get("notes"):
            slide.has_notes_slide = True
            note_shape = MagicMock()
            note_shape.text = slide_data["notes"]
            slide.notes_slide.shapes = [note_shape]
        else:
            slide.has_notes_slide = False

        mock_slides.append(slide)

    prs = MagicMock()
    prs.slides = mock_slides
    return prs


# ---------------------------------------------------------------------------
# ReadPptxTool — Schema tests
# ---------------------------------------------------------------------------


class TestReadPptxSchema:
    def test_name(self, tool):
        assert tool.name == "read_pptx"

    def test_readonly(self, tool):
        assert tool.readonly is True

    def test_description_nonempty(self, tool):
        assert len(tool.description) > 10

    def test_parameters_has_path(self, tool):
        params = tool.parameters
        assert params["type"] == "object"
        assert "path" in params["properties"]
        assert "path" in params["required"]

    def test_to_schema_format(self, tool):
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "read_pptx"


# ---------------------------------------------------------------------------
# ReadPptxTool — Execution tests
# ---------------------------------------------------------------------------


class TestReadPptxExecute:
    async def test_file_not_found(self, tool):
        result = await tool.execute(path="/nonexistent/deck.pptx")
        assert not result.success
        assert "not found" in result.output.lower()
        assert result.metadata.get("error_type") == "not_found"

    async def test_not_a_file(self, tool, tmp_path):
        d = tmp_path / "fake.pptx"
        d.mkdir()
        result = await tool.execute(path=str(d))
        assert not result.success
        assert result.metadata.get("error_type") == "invalid_path"

    async def test_wrong_extension(self, tool, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_text("not a pptx")
        result = await tool.execute(path=str(f))
        assert not result.success
        assert "not a .pptx" in result.output.lower()
        assert result.metadata.get("error_type") == "invalid_format"

    async def test_missing_dependency(self, tool, tmp_path):
        f = tmp_path / "deck.pptx"
        f.write_bytes(b"PK\x03\x04")
        with patch.dict(sys.modules, {"pptx": None}):
            with patch("builtins.__import__", side_effect=_make_import_error("pptx")):
                result = await tool.execute(path=str(f))
        assert not result.success
        assert "python-pptx" in result.output.lower()
        assert result.metadata.get("error_type") == "missing_dependency"

    async def test_extraction_success(self, tool, tmp_path, pptx_mod):
        f = tmp_path / "test.pptx"
        f.write_bytes(b"PK\x03\x04")
        mock_output = "# PowerPoint: test.pptx (2 slides)\n\n## Slide 1: Intro\nHello\n"
        with patch.object(pptx_mod, "_extract_pptx", return_value=mock_output):
            result = await tool.execute(path=str(f))
        assert result.success
        assert "Slide 1" in result.output
        assert "test.pptx" in result.output

    async def test_extraction_error(self, tool, tmp_path, pptx_mod):
        f = tmp_path / "bad.pptx"
        f.write_bytes(b"PK\x03\x04")
        with patch.object(pptx_mod, "_extract_pptx", side_effect=Exception("corrupt file")):
            result = await tool.execute(path=str(f))
        assert not result.success
        assert result.metadata.get("error_type") == "extraction_error"


# ---------------------------------------------------------------------------
# _extract_slides_data + _format_slides_markdown tests
# ---------------------------------------------------------------------------


class TestExtraction:
    def test_basic_extraction(self, pptx_mod, tmp_path):
        slides_data: list[dict[str, Any]] = [
            {"texts": ["Project Overview", "Q1 results are positive"]},
            {"texts": ["Budget", "Total: $1.2M"], "notes": "Approved by CFO"},
        ]
        mock_prs = _make_mock_presentation(slides_data)

        with patch.dict(sys.modules, {"pptx": MagicMock()}):
            with patch("pptx.Presentation", return_value=mock_prs):
                result = pptx_mod._extract_pptx(tmp_path / "deck.pptx")

        assert "deck.pptx" in result
        assert "2 slides" in result
        assert "Project Overview" in result
        assert "Budget" in result
        assert "Approved by CFO" in result
        assert "Slide 1" in result
        assert "Slide 2" in result

    def test_table_extraction(self, pptx_mod, tmp_path):
        slides_data: list[dict[str, Any]] = [
            {
                "texts": ["Data"],
                "tables": [[["Name", "Value"], ["Alpha", "100"], ["Beta", "200"]]],
            },
        ]
        mock_prs = _make_mock_presentation(slides_data)

        with patch.dict(sys.modules, {"pptx": MagicMock()}):
            with patch("pptx.Presentation", return_value=mock_prs):
                result = pptx_mod._extract_pptx(tmp_path / "deck.pptx")

        assert "Name | Value" in result
        assert "Alpha | 100" in result

    def test_empty_presentation(self, pptx_mod, tmp_path):
        empty: list[dict[str, Any]] = []
        mock_prs = _make_mock_presentation(empty)

        with patch.dict(sys.modules, {"pptx": MagicMock()}):
            with patch("pptx.Presentation", return_value=mock_prs):
                result = pptx_mod._extract_pptx(tmp_path / "empty.pptx")

        assert "0 slides" in result

    def test_structured_data_format(self, pptx_mod, tmp_path):
        """Verify _extract_slides_data returns proper structured dicts."""
        slides_data: list[dict[str, Any]] = [
            {"texts": ["Title", "Body text"], "notes": "Some notes"},
        ]
        mock_prs = _make_mock_presentation(slides_data)

        with patch.dict(sys.modules, {"pptx": MagicMock()}):
            with patch("pptx.Presentation", return_value=mock_prs):
                data = pptx_mod._extract_slides_data(tmp_path / "deck.pptx")

        assert len(data) == 1
        slide = data[0]
        assert slide["slide_number"] == 1
        assert "Title" in slide["title"]
        assert "Body text" in slide["text_blocks"]
        assert "Some notes" in slide["notes"]
        assert isinstance(slide["tables"], list)
        assert isinstance(slide["shape_types"], list)


# ---------------------------------------------------------------------------
# AnalyzePptxTool — Schema tests
# ---------------------------------------------------------------------------


class TestAnalyzePptxSchema:
    def test_name(self, analyze_tool):
        assert analyze_tool.name == "analyze_pptx"

    def test_not_readonly(self, analyze_tool):
        assert analyze_tool.readonly is False

    def test_description_nonempty(self, analyze_tool):
        assert len(analyze_tool.description) > 10

    def test_parameters(self, analyze_tool):
        params = analyze_tool.parameters
        assert params["type"] == "object"
        assert "path" in params["properties"]
        assert "model" in params["properties"]
        assert "output_path" in params["properties"]
        assert params["required"] == ["path"]

    def test_to_schema_format(self, analyze_tool):
        schema = analyze_tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "analyze_pptx"


# ---------------------------------------------------------------------------
# AnalyzePptxTool — Execution tests
# ---------------------------------------------------------------------------


class TestAnalyzePptxExecute:
    async def test_file_not_found(self, analyze_tool):
        result = await analyze_tool.execute(path="/nonexistent/deck.pptx")
        assert not result.success
        assert result.metadata.get("error_type") == "not_found"

    async def test_wrong_extension(self, analyze_tool, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_text("x")
        result = await analyze_tool.execute(path=str(f))
        assert not result.success
        assert result.metadata.get("error_type") == "invalid_format"

    async def test_empty_deck(self, analyze_tool, tmp_path, pptx_mod):
        f = tmp_path / "empty.pptx"
        f.write_bytes(b"PK\x03\x04")
        with patch.object(pptx_mod, "_extract_slides_data", return_value=[]):
            result = await analyze_tool.execute(path=str(f))
        assert result.success
        assert "no slides" in result.output.lower()

    async def test_analyze_text_only_mode(self, analyze_tool, tmp_path, pptx_mod):
        """Full pipeline with mocked internals – text-only mode."""
        f = tmp_path / "report.pptx"
        f.write_bytes(b"PK\x03\x04")
        out_json = tmp_path / "out.json"

        mock_slides = [
            {"slide_number": 1, "title": "Intro", "text_blocks": ["Hello"],
             "tables": [], "notes": "", "shape_types": []},
            {"slide_number": 2, "title": "Budget", "text_blocks": ["$1M"],
             "tables": [], "notes": "CFO approved", "shape_types": []},
        ]
        mock_slide_analysis = {
            "title": "Intro", "summary": "Introduction slide",
            "key_points": ["Overview"], "risks": [],
        }
        mock_synthesis = {
            "executive_summary": "A 2-slide deck about budget.",
            "risks": ["Budget overrun (slide 2)"],
            "decisions": ["Approved by CFO (slide 2)"],
            "action_items": ["Review Q2 budget"],
            "deadlines": ["Q2 2026"],
            "unanswered_questions": ["Who owns Q3?"],
            "themes": ["Budget"],
        }

        with (
            patch.object(pptx_mod, "_extract_slides_data", return_value=mock_slides),
            patch.object(pptx_mod, "_render_slides", new_callable=AsyncMock, return_value=None),
            patch.object(
                pptx_mod, "_analyze_slide", new_callable=AsyncMock,
                return_value=mock_slide_analysis,
            ),
            patch.object(
                pptx_mod, "_synthesize_deck", new_callable=AsyncMock,
                return_value=mock_synthesis,
            ),
        ):
            result = await analyze_tool.execute(
                path=str(f), output_path=str(out_json)
            )

        assert result.success
        assert "text-only" in result.output
        assert "Executive Summary" in result.output
        assert "Budget overrun" in result.output
        assert out_json.exists()

        saved = json.loads(out_json.read_text())
        assert saved["total_slides"] == 2
        assert saved["analysis_mode"] == "text-only"
        assert saved["executive_summary"] == mock_synthesis["executive_summary"]

    async def test_analyze_vision_mode(self, analyze_tool, tmp_path, pptx_mod):
        """Pipeline with mock rendering — should report vision mode."""
        f = tmp_path / "visual.pptx"
        f.write_bytes(b"PK\x03\x04")
        out_json = tmp_path / "vis.json"

        # Create fake rendered images
        imgs = []
        for i in range(2):
            img = tmp_path / f"slide-{i + 1}.png"
            img.write_bytes(b"\x89PNG fake")
            imgs.append(img)

        mock_slides = [
            {"slide_number": 1, "title": "Chart", "text_blocks": [],
             "tables": [], "notes": "", "shape_types": []},
            {"slide_number": 2, "title": "Summary", "text_blocks": [],
             "tables": [], "notes": "", "shape_types": []},
        ]
        mock_analysis = {"title": "Chart", "summary": "A chart slide"}
        mock_synthesis = {
            "executive_summary": "Visual deck.", "risks": [], "decisions": [],
            "action_items": [], "deadlines": [], "unanswered_questions": [],
            "themes": [],
        }

        with (
            patch.object(pptx_mod, "_extract_slides_data", return_value=mock_slides),
            patch.object(
                pptx_mod, "_render_slides", new_callable=AsyncMock, return_value=imgs,
            ),
            patch.object(
                pptx_mod, "_analyze_slide", new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
            patch.object(
                pptx_mod, "_synthesize_deck", new_callable=AsyncMock,
                return_value=mock_synthesis,
            ),
        ):
            result = await analyze_tool.execute(
                path=str(f), output_path=str(out_json)
            )

        assert result.success
        assert "vision" in result.output.lower()
        saved = json.loads(out_json.read_text())
        assert saved["analysis_mode"] == "vision"

    async def test_analyze_llm_failure(self, analyze_tool, tmp_path, pptx_mod):
        """LLM failure should return a clear error."""
        f = tmp_path / "fail.pptx"
        f.write_bytes(b"PK\x03\x04")

        mock_slides = [
            {"slide_number": 1, "title": "X", "text_blocks": ["Y"],
             "tables": [], "notes": "", "shape_types": []},
        ]

        with (
            patch.object(pptx_mod, "_extract_slides_data", return_value=mock_slides),
            patch.object(pptx_mod, "_render_slides", new_callable=AsyncMock, return_value=None),
            patch.object(
                pptx_mod, "_analyze_slide", new_callable=AsyncMock,
                side_effect=Exception("API key invalid"),
            ),
        ):
            result = await analyze_tool.execute(path=str(f))

        assert not result.success
        assert result.metadata.get("error_type") == "analysis_error"
        assert "API key" in result.output


# ---------------------------------------------------------------------------
# Rendering tests
# ---------------------------------------------------------------------------


class TestRenderSlides:
    async def test_no_rendering_deps(self, pptx_mod, tmp_path):
        """Returns None when soffice/pdftoppm are not on PATH."""
        with patch("shutil.which", return_value=None):
            result = await pptx_mod._render_slides(tmp_path / "x.pptx", tmp_path / "out")
        assert result is None


# ---------------------------------------------------------------------------
# LLM helpers tests
# ---------------------------------------------------------------------------


class TestParseJson:
    def test_valid_json(self, pptx_mod):
        result = pptx_mod._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_fence(self, pptx_mod):
        text = '```json\n{"key": "value"}\n```'
        result = pptx_mod._parse_json_response(text)
        assert result == {"key": "value"}

    def test_invalid_json_fallback(self, pptx_mod):
        """When json_repair also fails to produce a dict, raw_response is returned."""
        with patch.dict(sys.modules, {"json_repair": None}):
            with patch("builtins.__import__", side_effect=_make_import_error("json_repair")):
                result = pptx_mod._parse_json_response("not json at all")
        assert "raw_response" in result


class TestFormatAnalysis:
    def test_format_output(self, pptx_mod, tmp_path):
        synthesis = {
            "executive_summary": "This is the summary.",
            "risks": ["Risk A (slide 1)", "Risk B (slide 3)"],
            "decisions": ["Decision X (slide 2)"],
            "action_items": [],
            "deadlines": ["Q2 2026"],
            "unanswered_questions": [],
            "themes": ["Budget"],
        }
        out = tmp_path / "analysis.json"
        result = pptx_mod._format_analysis_output("deck.pptx", 5, "text-only", synthesis, out)
        assert "deck.pptx" in result
        assert "5 slides" in result
        assert "text-only" in result
        assert "Risk A" in result
        assert "Decision X" in result
        assert "Q2 2026" in result
        assert str(out) in result


# ---------------------------------------------------------------------------
# Path safety tests
# ---------------------------------------------------------------------------


class TestPathSafety:
    async def test_path_traversal_blocked(self, tool, pptx_mod):
        """Path traversal with allowed_dir should be blocked."""
        with pytest.raises(PermissionError, match="outside allowed directory"):
            pptx_mod._resolve_path("/etc/passwd", allowed_dir=Path("/home/user/workspace"))

    def test_resolve_path_normal(self, pptx_mod, tmp_path):
        f = tmp_path / "test.pptx"
        f.touch()
        resolved = pptx_mod._resolve_path(str(f))
        assert resolved == f.resolve()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_import_error(module_name: str):
    """Create a side_effect function that raises ImportError for a specific module."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _import(name, *args, **kwargs):
        if name == module_name:
            raise ImportError(f"No module named '{module_name}'")
        return real_import(name, *args, **kwargs)

    return _import
