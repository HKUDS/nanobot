"""Tests for LensClient - HTTP client for VS Code extension."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blackcat.config.schema import LensConfig, WorkspaceConfig
from blackcat.lens.client import LensClient


class TestLensClientInit:
    """Test LensClient initialization."""

    def test_init_creates_client(self):
        """Should create a LensClient with config."""
        config = LensConfig(enabled=True, workspaces={"test": "/tmp/test"})
        client = LensClient(config)

        assert client.config == config
        assert client.workspace_paths == {"test": "/tmp/test"}
        assert client._clients == {}

    def test_workspace_paths_normalizes_configs(self):
        """Should normalize WorkspaceConfig to paths."""
        config = LensConfig(
            enabled=True,
            workspaces={
                "simple": "/tmp/simple",
                "with-config": WorkspaceConfig(path="/tmp/with-config"),
            }
        )
        client = LensClient(config)

        paths = client.workspace_paths
        assert paths["simple"] == "/tmp/simple"
        assert paths["with-config"] == "/tmp/with-config"

    def test_get_diagnostics_source_default(self):
        """Should return default diagnostics_source."""
        config = LensConfig(enabled=True, diagnostics_source="cli")
        client = LensClient(config)

        assert client.get_diagnostics_source("unknown") == "cli"

    def test_get_diagnostics_source_per_workspace(self):
        """Should return per-workspace diagnostics_source if configured."""
        config = LensConfig(
            enabled=True,
            diagnostics_source="cli",
            workspaces={
                "vscode-ws": WorkspaceConfig(path="/tmp/vscode", diagnostics_source="vscode"),
            }
        )
        client = LensClient(config)

        assert client.get_diagnostics_source("vscode-ws") == "vscode"
        assert client.get_diagnostics_source("other") == "cli"


class TestLensClientPortResolution:
    """Test port resolution for workspaces."""

    def test_resolve_port_explicit_workspace(self):
        """Should resolve port for explicit workspace alias."""
        config = LensConfig(enabled=True, workspaces={"ws": "/tmp/ws"})
        client = LensClient(config)

        # Port is calculated deterministically from path
        port = client._resolve_port(workspace="ws")
        assert port > 0

    def test_resolve_port_file_path(self):
        """Should resolve port for file path within workspace."""
        config = LensConfig(enabled=True, workspaces={"ws": "/tmp/ws"})
        client = LensClient(config)

        port = client._resolve_port(file_path="/tmp/ws/file.py")
        assert port > 0

    def test_resolve_port_default(self):
        """Should return default port when no workspace or file."""
        config = LensConfig(enabled=True, port=9999)
        client = LensClient(config)

        port = client._resolve_port()
        # Default is always 8765 when no workspace/file matches
        assert port == 8765


class TestLensClientHttp:
    """Test HTTP client management."""

    def test_get_client_creates_cached(self):
        """Should create and cache HTTP client per port."""
        config = LensConfig(enabled=True, workspaces={"ws": "/tmp/ws"})
        client = LensClient(config)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            result1 = client._get_client(workspace="ws")
            result2 = client._get_client(workspace="ws")

            assert result1 is result2
            assert MockClient.call_count == 1

    def test_get_client_file_uri(self):
        """Should resolve port from file URI."""
        config = LensConfig(enabled=True, workspaces={"ws": "/tmp/ws"})
        client = LensClient(config)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            client._get_client(file_uri="file:///tmp/ws/file.py")

            assert MockClient.call_count == 1


class TestLensClientMethods:
    """Test LSP method wrappers."""

    @pytest.mark.asyncio
    async def test_is_healthy_success(self):
        """Should return True when health endpoint responds."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response

        client._clients[8765] = mock_client

        result = await client.is_healthy()
        assert result is True

    @pytest.mark.asyncio
    async def test_is_healthy_fallback(self):
        """Should use diagnostics as fallback health check."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500  # Still counts as healthy
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.post.return_value = mock_response

        client._clients[8765] = mock_client

        result = await client.is_healthy()
        assert result is True

    @pytest.mark.asyncio
    async def test_get_diagnostics_vscode(self):
        """Should call diagnostics endpoint for vscode source."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = [{"severity": "error", "message": "test"}]
        mock_client.post.return_value = mock_response

        client._clients[8765] = mock_client

        with patch.object(client, "_make_file_uri") as mock_uri:
            mock_uri.return_value = "file:///tmp/test.py"
            result = await client.get_diagnostics("/tmp/test.py", source="vscode")

        assert len(result) == 1
        assert result[0]["message"] == "test"

    @pytest.mark.asyncio
    async def test_get_diagnostics_cli(self):
        """Should call CLI diagnostics for cli source."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        with patch("blackcat.lens.cli_diagnostics.get_diagnostics_cli") as mock_cli:
            mock_cli.return_value = [{"severity": "warning"}]
            result = await client.get_diagnostics("/tmp/test.py", source="cli")

        assert len(result) == 1
        assert result[0]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_get_definition(self):
        """Should call definition endpoint."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = [{"uri": "file:///tmp/def.py"}]
        mock_client.post.return_value = mock_response

        client._clients[8765] = mock_client

        result = await client.get_definition("file:///tmp/test.py", 10, 5)

        assert len(result) == 1
        assert result[0]["uri"] == "file:///tmp/def.py"

    @pytest.mark.asyncio
    async def test_get_hover(self):
        """Should call hover endpoint."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"contents": "str"}
        mock_client.post.return_value = mock_response

        client._clients[8765] = mock_client

        result = await client.get_hover("file:///tmp/test.py", 10, 5)

        assert result is not None
        assert result["contents"] == "str"

    @pytest.mark.asyncio
    async def test_get_hover_none(self):
        """Should return None when hover returns empty."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = None
        mock_client.post.return_value = mock_response

        client._clients[8765] = mock_client

        result = await client.get_hover("file:///tmp/test.py", 10, 5)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_workspace_symbols(self):
        """Should call workspaceSymbol endpoint."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = [{"name": "foo"}]
        mock_client.post.return_value = mock_response

        client._clients[8765] = mock_client

        result = await client.get_workspace_symbols("foo")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_completion(self):
        """Should call completion endpoint."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_client.post.return_value = mock_response

        client._clients[8765] = mock_client

        result = await client.get_completion("file:///tmp/test.py", 10, 5)

        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_close(self):
        """Should close all HTTP clients."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        mock_client = AsyncMock()
        client._clients[8765] = mock_client

        await client.close()

        assert mock_client.aclose.called
        assert client._clients == {}


class TestLensClientPathHelpers:
    """Test path and URI helpers."""

    def test_resolve_path_with_workspace(self):
        """Should resolve path relative to workspace."""
        from pathlib import Path

        config = LensConfig(enabled=True, workspaces={"ws": "/tmp/ws"})
        client = LensClient(config)

        result = client.resolve_path("sub/file.py", workspace="ws")

        # Use Path comparison for cross-platform compatibility
        assert Path(result).name == "file.py"
        assert Path(result).parent.name == "sub"

    def test_resolve_path_without_workspace(self):
        """Should expand and resolve absolute path."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        result = client.resolve_path("~/test.py")

        assert result.is_absolute()

    def test_make_file_uri(self):
        """Should convert path to file:// URI."""
        config = LensConfig(enabled=True)
        client = LensClient(config)

        uri = client._make_file_uri("/tmp/test.py")

        # Path is resolved, so it will be absolute
        assert uri.startswith("file://")
        assert "test.py" in uri

    def test_get_workspace_for_file(self):
        """Should find workspace path and port for file."""
        from pathlib import Path

        config = LensConfig(enabled=True, workspaces={"ws": "/tmp/ws"})
        client = LensClient(config)

        result = client._get_workspace_for_file("/tmp/ws/file.py")

        # Returns (workspace_path, port) tuple or None
        assert result is not None
        workspace_path, port = result
        # Check path components for cross-platform compatibility
        assert Path(workspace_path).name == "ws"
        assert Path(workspace_path).parent.name == "tmp"
        assert isinstance(port, int)  # port number
