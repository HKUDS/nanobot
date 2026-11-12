"""Apply file edits by providing structured edit instructions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.agent.tools.filesystem import _FsTool  # pyright: ignore[reportPrivateUsage]
from nanobot.agent.tools.schema import (
    ArraySchema,
    BooleanSchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.utils.file_edit_events import FileDiff, FileEditResult, display_file_edit_path


class _PatchError(ValueError):
    pass


def _validate_patch_path(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        raise _PatchError("patch path cannot be empty")
    if "\0" in normalized:
        raise _PatchError(f"patch path contains a null byte: {path!r}")
    return normalized


def _append_text(content: str, addition: str) -> str:
    """Append text without merging it into an unterminated final line."""
    base = content.replace("\r\n", "\n")
    extra = addition.replace("\r\n", "\n")
    if base and extra and not base.endswith("\n") and not extra.startswith("\n"):
        base += "\n"
    combined = base + extra
    if combined and not combined.endswith("\n"):
        combined += "\n"
    return combined


@tool_parameters(
    tool_parameters_schema(
        edits=ArraySchema(
            items=ObjectSchema(
                path=StringSchema(
                    "Path to the file to edit. Relative paths resolve against the "
                    "workspace; absolute paths and '..' obey the workspace access policy."
                ),
                action=StringSchema(
                    "Operation type: replace or add.",
                    enum=["replace", "add"],
                ),
                old_text=StringSchema(
                    "Exact text to search for in the file. Required for replace.",
                    nullable=True,
                ),
                new_text=StringSchema(
                    "Text to replace with or append. Required for replace and add.",
                    nullable=True,
                ),
                required=["path", "action"],
            ),
            description="List of edits to apply. Each edit specifies a file and the change to make.",
            min_items=1,
            max_items=20,
        ),
        dry_run=BooleanSchema(
            description="Validate and summarize the patch without writing files.",
            default=False,
        ),
        required=["edits"],
    )
)
class ApplyPatchTool(_FsTool):
    """Apply file edits by providing structured edit instructions."""
    _scopes = {"core", "subagent"}

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "Default tool for code edits. Supports multi-file changes in a single call. "
            "Provide a list of structured edits, each specifying a file path, action "
            "(replace/add), and the exact text to change. "
            "Paths are resolved by the current workspace access policy. "
            "Set dry_run=true to validate and preview without writing files. "
            "Use edit_file only for small exact replacements on a single file."
        )

    async def execute(
        self,
        edits: list[object] | None = None,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            if not edits:
                raise _PatchError("must provide edits")

            writes: dict[Path, str] = {}
            originals: dict[Path, str] = {}
            actions: dict[Path, str] = {}

            for edit_value in edits:
                if not isinstance(edit_value, dict):
                    raise _PatchError("each edit must be an object")
                edit = cast(dict[str, Any], edit_value)
                raw_path = edit.get("path")
                if not isinstance(raw_path, str):
                    raise _PatchError("path required for edit")
                path = _validate_patch_path(raw_path)
                action = edit.get("action")
                if not isinstance(action, str):
                    raise _PatchError(f"action required for edit: {path}")
                source = self._resolve_write(path)

                if action == "add":
                    new_text = edit.get("new_text")
                    if new_text is None:
                        raise _PatchError(f"new_text required for add: {path}")
                    new_text = cast(str, new_text)

                    pending = writes.get(source)
                    if pending is not None:
                        content = pending
                        exists = True
                    elif source.exists():
                        raw = source.read_bytes()
                        try:
                            content = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            raise _PatchError(f"file is not UTF-8 text: {path}")
                        exists = True
                    else:
                        content = ""
                        exists = False

                    if exists:
                        uses_crlf = "\r\n" in content
                        new_norm = _append_text(content, new_text)
                        if uses_crlf:
                            new_norm = new_norm.replace("\n", "\r\n")
                        writes[source] = new_norm
                        action_name = "update"
                    else:
                        new_norm = new_text.replace("\r\n", "\n")
                        if new_norm and not new_norm.endswith("\n"):
                            new_norm += "\n"
                        writes[source] = new_norm
                        action_name = "add"

                elif action == "replace":
                    old_text = edit.get("old_text") or ""
                    if not old_text:
                        raise _PatchError(f"old_text required for replace: {path}")
                    old_text = cast(str, old_text)
                    new_text = edit.get("new_text")
                    if new_text is None:
                        raise _PatchError(f"new_text required for replace: {path}")
                    new_text = cast(str, new_text)

                    pending = writes.get(source)
                    if pending is not None:
                        content = pending
                    elif source.exists():
                        raw = source.read_bytes()
                        try:
                            content = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            raise _PatchError(f"file is not UTF-8 text: {path}")
                    else:
                        raise _PatchError(f"file to update does not exist: {path}")

                    if pending is None and not source.is_file():
                        raise _PatchError(f"path to update is not a file: {path}")

                    uses_crlf = "\r\n" in content
                    norm_content = content.replace("\r\n", "\n")
                    norm_old = old_text.replace("\r\n", "\n")

                    pos = norm_content.find(norm_old)
                    if pos < 0:
                        raise _PatchError(f"old_text not found in {path}")
                    if norm_content.find(norm_old, pos + 1) >= 0:
                        raise _PatchError(f"old_text appears multiple times in {path}")

                    new_norm = (
                        norm_content[:pos]
                        + new_text.replace("\r\n", "\n")
                        + norm_content[pos + len(norm_old) :]
                    )
                    if new_norm and not new_norm.endswith("\n"):
                        new_norm += "\n"
                    if uses_crlf:
                        new_norm = new_norm.replace("\n", "\r\n")

                    writes[source] = new_norm
                    action_name = "update"

                else:
                    raise _PatchError(f"unknown action: {action}")

                originals.setdefault(source, content)
                actions.setdefault(source, action_name)

            diffs = {
                source: FileDiff.from_text(originals[source], content)
                for source, content in writes.items()
            }
            summaries: list[str] = []
            for source, diff in diffs.items():
                action_name = actions[source]
                path = display_file_edit_path(source, self._display_workspace())
                added, deleted = diff.added, diff.deleted
                stats = f" (+{added}/-{deleted})" if added or deleted else ""
                summaries.append(f"- {action_name} {path}{stats}")

            if dry_run:
                return "Patch dry-run succeeded:\n" + "\n".join(summaries)

            backups: dict[Path, bytes | None] = {}
            for path in writes:
                backups[path] = path.read_bytes() if path.exists() else None

            try:
                for path, content in writes.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8", newline="")
            except Exception:
                for path, data in backups.items():
                    if data is None:
                        if path.exists():
                            path.unlink()
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                raise

            for path in writes:
                self._file_states.record_write(path)
            return FileEditResult("Patch applied:\n" + "\n".join(summaries), diffs)
        except PermissionError as exc:
            return ToolResult.error(f"Error: {exc}")
        except _PatchError as exc:
            return ToolResult.error(f"Error applying patch: {exc}")
        except Exception as exc:
            return ToolResult.error(f"Error applying patch: {exc}")
