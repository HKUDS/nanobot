"""Tests for Lens tools - LSP-based code intelligence tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blackcat.agent.tools.lens import (
    LensCodeActionTool,
    LensCompletionTool,
    LensDefinitionTool,
    LensDiagnosticsTool,
    LensDocumentSymbolTool,
    LensFormatTool,
    LensHoverTool,
    LensReferencesTool,
    LensRenameTool,
    LensSignatureHelpTool,
    LensWorkspaceSymbolTool,
)
from blackcat.config.schema import LensConfig
from blackcat.lens.client import LensClient


@pytest.fixture
def mock_lens_client():
    """Create a mock LensClient."""
    config = LensConfig(enabled=True, workspaces={"test": "/tmp/test"})
    client = LensClient(config)
    client._clients[8765] = AsyncMock()
    return client


class TestLensDefinitionTool:
    """Tests for lens_definition tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensDefinitionTool(AsyncMock())

        assert tool.name == "lens_definition"
        assert "defined" in tool.description.lower()

    def test_parameters_schema(self):
        """Should have correct parameter schema."""
        tool = LensDefinitionTool(AsyncMock())
        schema = tool.parameters

        assert schema["type"] == "object"
        assert "file_path" in schema["properties"]
        assert "line" in schema["properties"]
        assert "character" in schema["properties"]
        assert schema["required"] == ["file_path", "line", "character"]

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_lens_client):
        """Should return definition locations."""
        mock_lens_client.get_definition = AsyncMock(return_value=[
            {"uri": "file:///tmp/def.py", "range": {"start": {"line": 4, "character": 0}}}
        ])
        mock_lens_client.resolve_path = MagicMock(return_value="/tmp/test.py")

        tool = LensDefinitionTool(mock_lens_client)
        result = await tool.execute(file_path="test.py", line=10, character=5)

        assert "Definitions found" in result
        assert "/tmp/def.py:5:1" in result

    @pytest.mark.asyncio
    async def test_execute_not_found(self, mock_lens_client):
        """Should return not found message."""
        mock_lens_client.get_definition = AsyncMock(return_value=[])
        mock_lens_client.resolve_path = MagicMock(return_value="/tmp/test.py")

        tool = LensDefinitionTool(mock_lens_client)
        result = await tool.execute(file_path="test.py", line=10, character=5)

        assert "No definition found" in result

    @pytest.mark.asyncio
    async def test_execute_connection_error(self, mock_lens_client):
        """Should return connection error message."""
        # Simulate httpx ConnectError
        from httpx import ConnectError
        mock_lens_client.get_definition = AsyncMock(side_effect=ConnectError("Connection refused"))
        mock_lens_client.resolve_path = MagicMock(return_value="/tmp/test.py")
        mock_lens_client._make_file_uri = MagicMock(return_value="file:///tmp/test.py")

        tool = LensDefinitionTool(mock_lens_client)
        result = await tool.execute(file_path="test.py", line=10, character=5)

        assert "VS Code extension not running" in result


class TestLensReferencesTool:
    """Tests for lens_references tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensReferencesTool(AsyncMock())

        assert tool.name == "lens_references"
        assert "references" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_lens_client):
        """Should return reference locations."""
        mock_lens_client.get_references = AsyncMock(return_value=[
            {"uri": "file:///tmp/ref1.py", "range": {"start": {"line": 9, "character": 0}}},
            {"uri": "file:///tmp/ref2.py", "range": {"start": {"line": 19, "character": 5}}},
        ])
        mock_lens_client.resolve_path = MagicMock(return_value="/tmp/test.py")
        mock_lens_client._make_file_uri = MagicMock(return_value="file:///tmp/test.py")

        tool = LensReferencesTool(mock_lens_client)
        result = await tool.execute(file_path="test.py", line=10, character=5)

        assert "Found 2 references" in result
        assert "/tmp/ref1.py:10" in result
        assert "/tmp/ref2.py:20" in result


class TestLensHoverTool:
    """Tests for lens_hover tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensHoverTool(AsyncMock())

        assert tool.name == "lens_hover"
        assert "type" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_with_contents(self, mock_lens_client):
        """Should return hover contents."""
        mock_lens_client.get_hover = AsyncMock(return_value={
            "contents": {"value": "def foo() -> str"}
        })

        tool = LensHoverTool(mock_lens_client)
        result = await tool.execute(file_path="test.py", line=10, character=5)

        assert "def foo() -> str" in result

    @pytest.mark.asyncio
    async def test_execute_no_hover(self, mock_lens_client):
        """Should return no info message."""
        mock_lens_client.get_hover = AsyncMock(return_value=None)

        tool = LensHoverTool(mock_lens_client)
        result = await tool.execute(file_path="test.py", line=10, character=5)

        assert "No hover info" in result


class TestLensWorkspaceSymbolTool:
    """Tests for lens_workspace_symbol tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensWorkspaceSymbolTool(AsyncMock())

        assert tool.name == "lens_workspace_symbol"
        assert "symbol" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_lens_client):
        """Should return symbol search results."""
        mock_lens_client.get_workspace_symbols = AsyncMock(return_value=[
            {"name": "foo", "kind": "function", "location": {"uri": "file:///tmp/a.py"}},
            {"name": "Foo", "kind": "class", "location": {"uri": "file:///tmp/b.py"}},
        ])

        tool = LensWorkspaceSymbolTool(mock_lens_client)
        result = await tool.execute(query="foo")

        assert "Found 2 symbols" in result
        assert "foo" in result
        assert "Foo" in result


class TestLensDocumentSymbolTool:
    """Tests for lens_document_symbol tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensDocumentSymbolTool(AsyncMock())

        assert tool.name == "lens_document_symbol"
        assert "outline" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_lens_client):
        """Should return document symbols."""
        mock_lens_client.get_document_symbols = AsyncMock(return_value=[
            {"name": "MyClass", "kind": "class", "range": {"start": {"line": 0}}},
            {"name": "my_method", "kind": "method", "range": {"start": {"line": 5}}},
        ])
        mock_lens_client.resolve_path = MagicMock(return_value="/tmp/test.py")
        mock_lens_client._make_file_uri = MagicMock(return_value="file:///tmp/test.py")

        tool = LensDocumentSymbolTool(mock_lens_client)
        result = await tool.execute(file_path="test.py")

        assert "Symbols in" in result
        assert "MyClass" in result
        assert "my_method" in result


class TestLensCompletionTool:
    """Tests for lens_completion tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensCompletionTool(AsyncMock())

        assert tool.name == "lens_completion"
        assert "completion" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_lens_client):
        """Should return completion items."""
        mock_lens_client.get_completion = AsyncMock(return_value={
            "items": [
                {"label": "foo", "kind": "function"},
                {"label": "bar", "kind": "variable"},
            ]
        })
        mock_lens_client.resolve_path = MagicMock(return_value="/tmp/test.py")
        mock_lens_client._make_file_uri = MagicMock(return_value="file:///tmp/test.py")

        tool = LensCompletionTool(mock_lens_client)
        result = await tool.execute(file_path="test.py", line=10, character=5)

        assert "Found 2 completions" in result
        assert "foo" in result


class TestLensRenameTool:
    """Tests for lens_rename tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensRenameTool(AsyncMock())

        assert tool.name == "lens_rename"
        assert "rename" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_lens_client):
        """Should return rename preview."""
        mock_lens_client.get_rename_edits = AsyncMock(return_value={
            "changes": {
                "file:///tmp/a.py": [{"range": {"start": {"line": 0}}, "newText": "new_name"}]
            }
        })
        mock_lens_client.resolve_path = MagicMock(return_value="/tmp/test.py")
        mock_lens_client._make_file_uri = MagicMock(return_value="file:///tmp/test.py")

        tool = LensRenameTool(mock_lens_client)
        result = await tool.execute(file_path="test.py", line=10, character=5, new_name="new_name")

        assert "Rename preview" in result
        assert "1 files affected" in result


class TestLensCodeActionTool:
    """Tests for lens_code_action tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensCodeActionTool(AsyncMock())

        assert tool.name == "lens_code_action"
        assert "quick fix" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_lens_client):
        """Should return code actions."""
        mock_lens_client.get_code_actions = AsyncMock(return_value=[
            {"title": "Import missing module", "kind": "quickfix"},
            {"title": "Extract method", "kind": "refactor"},
        ])
        mock_lens_client.resolve_path = MagicMock(return_value="/tmp/test.py")
        mock_lens_client._make_file_uri = MagicMock(return_value="file:///tmp/test.py")

        tool = LensCodeActionTool(mock_lens_client)
        result = await tool.execute(
            file_path="test.py",
            start_line=10,
            start_character=0,
            end_line=10,
            end_character=5,
        )

        assert "Found 2 code actions" in result
        assert "Import missing module" in result


class TestLensFormatTool:
    """Tests for lens_format tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensFormatTool(AsyncMock())

        assert tool.name == "lens_format"
        assert "format" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_lens_client):
        """Should return formatting info."""
        mock_lens_client.get_formatting = AsyncMock(return_value=[
            {"range": {"start": {"line": 0}}, "newText": "formatted"}
        ])

        tool = LensFormatTool(mock_lens_client)
        result = await tool.execute(file_path="test.py")

        assert "Formatting" in result


class TestLensSignatureHelpTool:
    """Tests for lens_signature_help tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensSignatureHelpTool(AsyncMock())

        assert tool.name == "lens_signature_help"
        assert "signature" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_lens_client):
        """Should return signature help."""
        mock_lens_client.get_signature_help = AsyncMock(return_value={
            "signatures": [
                {"label": "foo(a: int, b: str) -> str", "documentation": "Does foo"}
            ]
        })

        tool = LensSignatureHelpTool(mock_lens_client)
        result = await tool.execute(file_path="test.py", line=10, character=5)

        assert "Signature" in result
        assert "foo(a: int, b: str) -> str" in result


class TestLensDiagnosticsTool:
    """Tests for lens_diagnostics tool."""

    def test_name_and_description(self):
        """Should have correct name and description."""
        tool = LensDiagnosticsTool(AsyncMock())

        assert tool.name == "lens_diagnostics"
        assert "diagnostic" in tool.description.lower()

    def test_parameters_schema(self):
        """Should have correct parameter schema."""
        tool = LensDiagnosticsTool(AsyncMock(), default_source="vscode")
        schema = tool.parameters

        assert "file_path" in schema["properties"]
        assert "workspace" in schema["properties"]
        assert "source" in schema["properties"]

    @pytest.mark.asyncio
    async def test_execute_with_errors(self, mock_lens_client):
        """Should return formatted diagnostics."""
        mock_lens_client.get_diagnostics = AsyncMock(return_value=[
            {"severity": "error", "message": "Undefined name 'x'", "range": {"start": {"line": 4}}},
        ])
        mock_lens_client.resolve_path = MagicMock(return_value="/tmp/test.py")
        mock_lens_client.get_diagnostics_source = MagicMock(return_value="cli")

        tool = LensDiagnosticsTool(mock_lens_client)
        result = await tool.execute(file_path="test.py")

        assert "Undefined name" in result
