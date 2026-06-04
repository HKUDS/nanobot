from __future__ import annotations

from typing import Any

from blackcat.agent.tools.base import Tool
from blackcat.lens import LensClient
from blackcat.utils.paths import resolve_path


class LensDefinitionTool(Tool):
    """Find symbol definition via LSP."""

    @property
    def name(self) -> str:
        return "lens_definition"

    @property
    def description(self) -> str:
        return (
            "Find where a symbol (function, class, variable) is defined. "
            "Use this when you need to understand the implementation of something "
            "or navigate to the source of a symbol."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file containing the symbol",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-indexed) where the symbol is",
                },
                "character": {
                    "type": "integer",
                    "description": "Character position (0-indexed) in the line",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config (e.g., 'black-cat-py')",
                },
            },
            "required": ["file_path", "line", "character"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        line = kwargs["line"]
        character = kwargs["character"]
        workspace = kwargs.get("workspace")
        try:
            full_path = resolve_path(file_path, workspace)
            uri = self.client._make_file_uri(full_path)
            locations = await self.client.get_definition(uri, line, character)

            if not locations:
                return f"No definition found for symbol at {file_path}:{line}:{character}"

            lines = ["Definitions found:"]
            for loc in locations:
                uri = loc.get("uri", "")
                range_info = loc.get("range", {})
                start = range_info.get("start", {})
                line_num = start.get("line", 0) + 1
                char_num = start.get("character", 0) + 1
                # Convert file:// URI to readable path
                path = uri.replace("file://", "") if uri.startswith("file://") else uri
                lines.append(f"- {path}:{line_num}:{char_num}")

            return "\n".join(lines)

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running. Start it with 'blackcat: Start LSP Bridge' command."
            return f"Error finding definition: {str(e)}"


class LensReferencesTool(Tool):
    """Find all references to a symbol."""

    @property
    def name(self) -> str:
        return "lens_references"

    @property
    def description(self) -> str:
        return (
            "Find all references to a symbol across the codebase. "
            "Use this when you need to understand where a function, class, or variable is used."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file containing the symbol",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-indexed) where the symbol is",
                },
                "character": {
                    "type": "integer",
                    "description": "Character position (0-indexed) in the line",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config",
                },
            },
            "required": ["file_path", "line", "character"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        line = kwargs["line"]
        character = kwargs["character"]
        workspace = kwargs.get("workspace")
        try:
            full_path = resolve_path(file_path, workspace)
            uri = self.client._make_file_uri(full_path)
            locations = await self.client.get_references(uri, line, character)

            if not locations:
                return f"No references found for symbol at {file_path}:{line}:{character}"

            lines = [f"Found {len(locations)} references:"]
            for loc in locations[:20]:  # Limit output
                uri = loc.get("uri", "")
                range_info = loc.get("range", {})
                start = range_info.get("start", {})
                line_num = start.get("line", 0) + 1
                path = uri.replace("file://", "") if uri.startswith("file://") else uri
                lines.append(f"- {path}:{line_num}")

            if len(locations) > 20:
                lines.append(f"- ... and {len(locations) - 20} more")

            return "\n".join(lines)

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error finding references: {str(e)}"


class LensHoverTool(Tool):
    """Get type information and documentation for a symbol."""

    @property
    def name(self) -> str:
        return "lens_hover"

    @property
    def description(self) -> str:
        return (
            "Get type information and documentation for a symbol under the cursor. "
            "Use this when you need to understand what a variable or function is."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-indexed)",
                },
                "character": {
                    "type": "integer",
                    "description": "Character position (0-indexed)",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config",
                },
            },
            "required": ["file_path", "line", "character"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        line = kwargs["line"]
        character = kwargs["character"]
        workspace = kwargs.get("workspace")
        try:
            full_path = resolve_path(file_path, workspace)
            uri = self.client._make_file_uri(full_path)
            hover = await self.client.get_hover(uri, line, character)

            if not hover:
                return f"No hover information at {file_path}:{line}:{character}"

            contents = hover.get("contents", "")
            return f"Type information:\n{contents}"

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error getting hover info: {str(e)}"


class LensWorkspaceSymbolTool(Tool):
    """Search for symbols across the workspace."""

    @property
    def name(self) -> str:
        return "lens_workspace_symbol"

    @property
    def description(self) -> str:
        return (
            "Search for symbols (functions, classes, variables) across the entire workspace. "
            "Use this when you need to find something by name."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Symbol name to search for (e.g., 'AgentLoop', 'build_messages')",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config (e.g., 'black-cat-py')",
                },
            },
            "required": ["query"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        workspace = kwargs.get("workspace")
        try:
            symbols = await self.client.get_workspace_symbols(query, workspace)

            if not symbols:
                return f"No symbols found matching '{query}'"

            lines = [f"Found {len(symbols)} symbols:"]
            for sym in symbols[:15]:
                name = sym.get("name", "")
                kind = sym.get("kind", "")
                container = sym.get("containerName", "")
                loc = sym.get("location", {})
                uri = loc.get("uri", "")
                path = uri.replace("file://", "") if uri.startswith("file://") else uri

                prefix = f"{container}." if container else ""
                lines.append(f"- {prefix}{name} ({kind}) in {path}")

            if len(symbols) > 15:
                lines.append(f"- ... and {len(symbols) - 15} more")

            return "\n".join(lines)

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error searching symbols: {str(e)}"


class LensDocumentSymbolTool(Tool):
    """Get document outline (symbols)."""

    @property
    def name(self) -> str:
        return "lens_document_symbol"

    @property
    def description(self) -> str:
        return (
            "Get the outline of a document - all classes, functions, and variables defined in it. "
            "Use this to understand the structure of a file."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config",
                },
            },
            "required": ["file_path"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        workspace = kwargs.get("workspace")
        try:
            full_path = resolve_path(file_path, workspace)
            uri = self.client._make_file_uri(full_path)
            symbols = await self.client.get_document_symbols(uri)

            if not symbols:
                return f"No symbols found in {file_path}"

            lines = [f"Symbols in {file_path}:", ""]

            def format_symbol(sym, indent=0):
                name = sym.get("name", "")
                detail = sym.get("detail", "")
                prefix = "  " * indent
                info = f" ({detail})" if detail else ""
                lines.append(f"{prefix}- {name}{info}")
                for child in sym.get("children", []):
                    format_symbol(child, indent + 1)

            for sym in symbols:
                format_symbol(sym)

            return "\n".join(lines)

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error getting document symbols: {str(e)}"


class LensCompletionTool(Tool):
    """Get code completion suggestions at cursor position."""

    @property
    def name(self) -> str:
        return "lens_completion"

    @property
    def description(self) -> str:
        return (
            "Get autocomplete suggestions at a specific cursor position. "
            "Use this when you want to see what methods, properties, or completions are available."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-indexed) where cursor is",
                },
                "character": {
                    "type": "integer",
                    "description": "Character position (0-indexed) in the line",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config",
                },
            },
            "required": ["file_path", "line", "character"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        line = kwargs["line"]
        character = kwargs["character"]
        workspace = kwargs.get("workspace")
        try:
            full_path = resolve_path(file_path, workspace)
            uri = self.client._make_file_uri(full_path)
            result = await self.client.get_completion(uri, line, character)

            items = result.get("items", [])
            if not items:
                return f"No completions found at {file_path}:{line}:{character}"

            lines = [f"Found {len(items)} completions:"]
            for item in items[:20]:
                label = item.get("label", "")
                item_kind = item.get("kind", "")
                detail = item.get("detail", "")
                doc = item.get("documentation", "")
                kind_info = f" [{item_kind}]" if item_kind else ""
                info = f" ({detail})" if detail else ""
                lines.append(f"- {label}{kind_info}{info}")
                if doc:
                    lines.append(f"  {doc[:100]}..." if len(str(doc)) > 100 else f"  {doc}")

            if len(items) > 20:
                lines.append(f"- ... and {len(items) - 20} more")

            return "\n".join(lines)

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error getting completions: {str(e)}"


class LensRenameTool(Tool):
    """Rename a symbol across the entire codebase."""

    @property
    def name(self) -> str:
        return "lens_rename"

    @property
    def description(self) -> str:
        return (
            "Rename a symbol (variable, function, class) across the entire codebase. "
            "Shows a preview of all files that would be modified. "
            "Use this for refactoring when you need to rename something that appears in multiple files."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file containing the symbol",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-indexed) where the symbol is",
                },
                "character": {
                    "type": "integer",
                    "description": "Character position (0-indexed) in the line",
                },
                "new_name": {
                    "type": "string",
                    "description": "New name for the symbol",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config",
                },
            },
            "required": ["file_path", "line", "character", "new_name"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        line = kwargs["line"]
        character = kwargs["character"]
        new_name = kwargs["new_name"]
        workspace = kwargs.get("workspace")
        try:
            full_path = resolve_path(file_path, workspace)
            uri = self.client._make_file_uri(full_path)
            result = await self.client.get_rename_edits(uri, line, character, new_name)

            if not result:
                return f"Cannot rename symbol at {file_path}:{line}:{character}"

            changes = result.get("changes", {})
            if not changes:
                return "No changes needed"

            lines = [f"Rename preview ({len(changes)} files affected):"]
            for uri, edits in changes.items():
                path = uri.replace("file://", "") if uri.startswith("file://") else uri
                lines.append(f"\n{path}: {len(edits)} edits")
                for edit in edits[:5]:
                    range_info = edit.get("range", {})
                    start = range_info.get("start", {})
                    line_num = start.get("line", 0) + 1
                    lines.append(f"  - line {line_num}")
                if len(edits) > 5:
                    lines.append(f"  - ... and {len(edits) - 5} more")

            return "\n".join(lines)

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error during rename: {str(e)}"


class LensCodeActionTool(Tool):
    """Get quick fixes and refactorings for a code range."""

    @property
    def name(self) -> str:
        return "lens_code_action"

    @property
    def description(self) -> str:
        return (
            "Get quick fixes and code actions for a selected range. "
            "Use this for 'import missing module', 'remove unused import', 'extract method', etc. "
            "Shows available refactorings and quick fixes."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line (0-indexed)",
                },
                "start_character": {
                    "type": "integer",
                    "description": "Start character position",
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line (0-indexed)",
                },
                "end_character": {
                    "type": "integer",
                    "description": "End character position",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config",
                },
            },
            "required": ["file_path", "start_line", "start_character", "end_line", "end_character"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        start_line = kwargs["start_line"]
        start_character = kwargs["start_character"]
        end_line = kwargs["end_line"]
        end_character = kwargs["end_character"]
        workspace = kwargs.get("workspace")
        try:
            full_path = resolve_path(file_path, workspace)
            uri = self.client._make_file_uri(full_path)
            actions = await self.client.get_code_actions(
                uri, start_line, start_character, end_line, end_character
            )

            if not actions:
                return f"No code actions available for that range in {file_path}"

            lines = [f"Found {len(actions)} code actions:"]
            for action in actions[:15]:
                title = action.get("title", "")
                kind = action.get("kind", "")
                has_edit = action.get("edit", False)
                edit_info = " (has edits)" if has_edit else ""
                kind_info = f" [{kind}]" if kind else ""
                lines.append(f"- {title}{kind_info}{edit_info}")

            if len(actions) > 15:
                lines.append(f"- ... and {len(actions) - 15} more")

            return "\n".join(lines)

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error getting code actions: {str(e)}"


class LensFormatTool(Tool):
    """Format a document using the LSP formatter."""

    @property
    def name(self) -> str:
        return "lens_format"

    @property
    def description(self) -> str:
        return (
            "Format a document using the LSP formatter (same as VS Code's format document). "
            "Shows the formatting changes that would be applied. "
            "Use this to see formatting edits without applying them directly."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to format",
                },
                "tab_size": {
                    "type": "integer",
                    "default": 4,
                    "description": "Number of spaces per tab",
                },
                "insert_spaces": {
                    "type": "boolean",
                    "default": True,
                    "description": "Use spaces instead of tabs",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config",
                },
            },
            "required": ["file_path"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        tab_size = kwargs.get("tab_size", 4)
        insert_spaces = kwargs.get("insert_spaces", True)
        workspace = kwargs.get("workspace")
        try:
            full_path = resolve_path(file_path, workspace)
            uri = self.client._make_file_uri(full_path)
            edits = await self.client.get_formatting(uri, tab_size, insert_spaces)

            if not edits:
                return f"No formatting changes needed for {file_path}"

            lines = [f"Formatting would make {len(edits)} edits:"]
            for edit in edits[:10]:
                range_info = edit.get("range", {})
                start = range_info.get("start", {})
                line_num = start.get("line", 0) + 1
                new_text = edit.get("newText", "")
                text_preview = new_text[:40] + "..." if len(new_text) > 40 else new_text
                lines.append(f"- Line {line_num}: {repr(text_preview)}")

            if len(edits) > 10:
                lines.append(f"- ... and {len(edits) - 10} more edits")

            return "\n".join(lines)

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error formatting: {str(e)}"


class LensSignatureHelpTool(Tool):
    """Get function signature help as you type."""

    @property
    def name(self) -> str:
        return "lens_signature_help"

    @property
    def description(self) -> str:
        return (
            "Get function signature information including parameter names and types. "
            "Use this when you're inside a function call and want to see what parameters it accepts. "
            "Shows active parameter and documentation."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-indexed) where cursor is inside function call",
                },
                "character": {
                    "type": "integer",
                    "description": "Character position (0-indexed) in the line",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config",
                },
            },
            "required": ["file_path", "line", "character"],
        }

    def __init__(self, client: LensClient):
        self.client = client

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        line = kwargs["line"]
        character = kwargs["character"]
        workspace = kwargs.get("workspace")
        try:
            full_path = resolve_path(file_path, workspace)
            uri = self.client._make_file_uri(full_path)
            result = await self.client.get_signature_help(uri, line, character)

            if not result:
                return f"No signature help available at {file_path}:{line}:{character}"

            signatures = result.get("signatures", [])
            active_sig = result.get("activeSignature", 0)
            active_param = result.get("activeParameter", 0)

            if not signatures:
                return "No signature information found"

            lines = []
            for i, sig in enumerate(signatures[:3]):
                label = sig.get("label", "")
                doc = sig.get("documentation", "")
                params = sig.get("parameters", [])

                marker = " <- current" if i == active_sig else ""
                lines.append(f"Signature {i + 1}{marker}:")
                lines.append(f"  {label}")

                if params and i == active_sig:
                    lines.append("  Parameters:")
                    for j, param in enumerate(params):
                        param_label = param.get("label", "")
                        param_doc = param.get("documentation", "")
                        active_marker = " <- active" if j == active_param else ""
                        lines.append(f"    - {param_label}{active_marker}")
                        if param_doc:
                            lines.append(f"      {param_doc}")

                if doc:
                    lines.append(f"  Docs: {doc[:200]}..." if len(str(doc)) > 200 else f"  Docs: {doc}")
                lines.append("")

            return "\n".join(lines).rstrip()

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error getting signature help: {str(e)}"


class LensDiagnosticsTool(Tool):
    """Get diagnostics (errors, warnings) for a file."""

    @property
    def name(self) -> str:
        return "lens_diagnostics"

    @property
    def description(self) -> str:
        return (
            "Get diagnostics (errors, warnings, hints) for a file. "
            "Use this to check code health and see issues like type errors, missing imports, "
            "or linting problems. "
            "Source defaults to config.tools.lens.diagnostics_source ('vscode' or 'cli'). "
            "CLI gives fresh results but may fail on large/broken codebases; "
            "VSCode is faster but may be stale for TypeScript."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to check",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace name from config (e.g., 'black-cat-py')",
                },
                "source": {
                    "type": "string",
                    "enum": ["cli", "vscode"],
                    "description": "Source: 'cli' (fresh, slower) or 'vscode' (cached, faster)",
                },
            },
            "required": ["file_path"],
        }

    def __init__(self, client: LensClient, default_source: str = "cli"):
        self.client = client
        self.default_source = default_source

    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs["file_path"]
        workspace = kwargs.get("workspace")
        source = kwargs.get("source")
        """Get diagnostics for a file.

        Args:
            file_path: Path to file (relative to workspace or absolute)
            workspace: Workspace alias from config
            source: "cli" (fresh, bypasses VSCode) or "vscode" (cached, faster).
                    Defaults to per-workspace override or global config.
        """
        # Determine source: explicit > per-workspace override > global default
        if source:
            actual_source = source
        elif workspace:
            actual_source = self.client.get_diagnostics_source(workspace)
        else:
            actual_source = self.default_source

        try:
            full_path = resolve_path(file_path, workspace)
            diagnostics = await self.client.get_diagnostics(
                str(full_path), workspace, source=actual_source
            )

            if not diagnostics:
                return f"No diagnostics for {file_path}"

            from blackcat.lens.formatting import format_diagnostics

            return format_diagnostics(diagnostics)

        except Exception as e:
            if "ConnectError" in str(type(e)):
                return "Error: VS Code extension not running."
            return f"Error getting diagnostics: {str(e)}"
