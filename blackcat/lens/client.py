"""Lens HTTP client for VS Code extension."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .discovery import find_workspace_for_file, get_port_for_workspace

if TYPE_CHECKING:
    from blackcat.config.schema import LensConfig


class LensClient:
    """HTTP client for lens VS Code extension."""

    def __init__(self, config: "LensConfig"):
        from httpx import AsyncClient

        self.config = config
        self._clients: dict[int, AsyncClient] = {}

    @property
    def workspace_paths(self) -> dict[str, str]:
        """Normalized workspace name -> path mapping."""
        return self.config.get_workspace_paths()

    def get_diagnostics_source(self, workspace: str) -> str:
        """Get diagnostics_source for a workspace."""
        return self.config.get_workspace_source(workspace)

    def _get_client(self, workspace: str | None = None, file_uri: str | None = None):
        """Get or create HTTP client for a workspace or file."""
        from httpx import AsyncClient

        # Extract file_path from file_uri for workspace discovery
        file_path: str | None = None
        if file_uri and file_uri.startswith("file://"):
            file_path = file_uri[7:]

        port = self._resolve_port(workspace, file_path)
        if port not in self._clients:
            base_url = f"http://localhost:{port}"
            self._clients[port] = AsyncClient(base_url=base_url, timeout=10.0)
        return self._clients[port]

    async def _request(
        self,
        method: str,
        params: dict,
        workspace: str | None = None,
        file_uri: str | None = None,
    ) -> Any:
        """Make an LSP request and return the JSON result."""
        client = self._get_client(workspace, file_uri)
        response = await client.post("/", json={"method": method, "params": params})
        response.raise_for_status()
        return response.json()

    def _resolve_port(self, workspace: str | None = None, file_path: str | None = None) -> int:
        """Resolve port for a workspace.

        Priority:
        1. Explicit workspace alias
        2. File path -> workspace discovery
        3. Default port
        """
        workspace_paths = self.workspace_paths
        if workspace and workspace in workspace_paths:
            workspace_path = workspace_paths[workspace]
            port = get_port_for_workspace(workspace_path)
            if port:
                return port

        if file_path:
            result = find_workspace_for_file(file_path, workspace_paths)
            if result:
                _, port = result
                return port

        # Default port from config or fallback
        return getattr(self.config, "port", 8765)

    def _get_workspace_for_file(self, file_path: str) -> tuple[str, int] | None:
        """Find workspace alias and port for a file path."""
        workspace_paths = self.workspace_paths
        result = find_workspace_for_file(file_path, workspace_paths)
        if result:
            return result

        # Fallback: check if file is under any configured workspace
        for alias, path in workspace_paths.items():
            if file_path.startswith(path):
                port = get_port_for_workspace(path)
                if port:
                    return (alias, port)
        return None

    async def is_healthy(self, workspace: str | None = None) -> bool:
        """Check if VS Code extension is running."""
        client = self._get_client(workspace)
        try:
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            try:
                response = await client.post(
                    "/",
                    json={"method": "diagnostics", "params": {"uri": "file:///test"}},
                )
                return response.status_code in (200, 500)
            except Exception:
                return False

    def resolve_path(self, path: str, workspace: str | None = None) -> Path:
        """Resolve a path, optionally relative to a workspace.

        Args:
            path: File path to resolve
            workspace: Workspace alias to resolve against

        Returns:
            Resolved Path object
        """
        p = Path(path).expanduser()
        if workspace and workspace in self.workspace_paths:
            p = Path(self.workspace_paths[workspace]) / p
        return p.resolve()

    def _make_file_uri(self, file_path: str | Path) -> str:
        """Convert path to file:// URI."""
        p = Path(file_path).expanduser().resolve()
        return f"file://{p}"

    async def get_diagnostics(
        self,
        file_path: str,
        workspace: str | None = None,
        source: str = "vscode",
    ) -> list[dict]:
        """Get diagnostics (errors/warnings) for a file.

        Args:
            file_path: Path to file
            workspace: Workspace alias or path
            source: "vscode" (cached, fast) or "cli" (fresh, slower)

        Returns:
            List of diagnostic dicts
        """
        if source == "cli":
            from .cli_diagnostics import get_diagnostics_cli

            ws_path = None
            if workspace and workspace in self.workspace_paths:
                ws_path = self.workspace_paths[workspace]
            return await get_diagnostics_cli(file_path, ws_path)

        # VSCode extension (cached diagnostics)
        uri = self._make_file_uri(file_path)
        return await self._request("diagnostics", {"uri": uri}, workspace, uri)

    async def get_definition(
        self, file_uri: str, line: int, character: int, workspace: str | None = None
    ) -> list[dict]:
        """Find symbol definition."""
        return await self._request(
            "definition",
            {"uri": file_uri, "position": {"line": line, "character": character}},
            workspace,
            file_uri,
        )

    async def get_references(
        self, file_uri: str, line: int, character: int, workspace: str | None = None
    ) -> list[dict]:
        """Find all references to a symbol."""
        return await self._request(
            "references",
            {"uri": file_uri, "position": {"line": line, "character": character}},
            workspace,
            file_uri,
        )

    async def get_hover(
        self, file_uri: str, line: int, character: int, workspace: str | None = None
    ) -> dict | None:
        """Get hover info (type, docs) for a symbol."""
        result = await self._request(
            "hover",
            {"uri": file_uri, "position": {"line": line, "character": character}},
            workspace,
            file_uri,
        )
        return result if result else None

    async def get_workspace_symbols(self, query: str, workspace: str | None = None) -> list[dict]:
        """Search symbols across workspace."""
        return await self._request("workspaceSymbol", {"query": query}, workspace)

    async def get_document_symbols(self, file_uri: str, workspace: str | None = None) -> list[dict]:
        """Get document outline (symbols)."""
        return await self._request("documentSymbol", {"uri": file_uri}, workspace, file_uri)

    async def get_completion(
        self, file_uri: str, line: int, character: int, workspace: str | None = None
    ) -> dict:
        """Get completion suggestions at position."""
        return await self._request(
            "completion",
            {"uri": file_uri, "position": {"line": line, "character": character}},
            workspace,
            file_uri,
        )

    async def get_rename_edits(
        self, file_uri: str, line: int, character: int, new_name: str, workspace: str | None = None
    ) -> dict | None:
        """Get workspace edits for renaming a symbol."""
        result = await self._request(
            "rename",
            {
                "uri": file_uri,
                "position": {"line": line, "character": character},
                "newName": new_name,
            },
            workspace,
            file_uri,
        )
        return result if result else None

    async def get_code_actions(
        self,
        file_uri: str,
        start_line: int,
        start_char: int,
        end_line: int,
        end_char: int,
        workspace: str | None = None,
    ) -> list[dict]:
        """Get code actions (quick fixes) for a range."""
        return await self._request(
            "codeAction",
            {
                "uri": file_uri,
                "range": {
                    "start": {"line": start_line, "character": start_char},
                    "end": {"line": end_line, "character": end_char},
                },
            },
            workspace,
            file_uri,
        )

    async def get_formatting(
        self, file_uri: str, tab_size: int = 4, insert_spaces: bool = True, workspace: str | None = None
    ) -> list[dict]:
        """Get formatting edits for a document."""
        return await self._request(
            "format",
            {"uri": file_uri, "options": {"tabSize": tab_size, "insertSpaces": insert_spaces}},
            workspace,
            file_uri,
        )

    async def get_signature_help(
        self, file_uri: str, line: int, character: int, workspace: str | None = None
    ) -> dict | None:
        """Get signature help for a function call."""
        result = await self._request(
            "signatureHelp",
            {"uri": file_uri, "position": {"line": line, "character": character}},
            workspace,
            file_uri,
        )
        return result if result else None

    async def close(self):
        """Close all HTTP clients."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
