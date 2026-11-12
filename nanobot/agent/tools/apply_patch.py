from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, cast

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.agent.tools.filesystem import _WritableFsTool  # pyright: ignore[reportPrivateUsage]
from nanobot.agent.tools.schema import (
    ArraySchema,
    BooleanSchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.execution.files import WritableFile, commit_file_edits
from nanobot.utils.file_edit_events import FileDiff, FileEditResult, display_file_edit_path


class _PatchError(ValueError):
    pass


def _validate_patch_path(path: object) -> str:
    if not isinstance(path, str):
        raise _PatchError("path required for edit")
    normalized = path.strip()
    if not normalized:
        raise _PatchError("patch path cannot be empty")
    if "\0" in normalized:
        raise _PatchError(f"patch path contains a null byte: {path!r}")
    return normalized


@tool_parameters(
    tool_parameters_schema(
        edits=ArraySchema(
            items=ObjectSchema(
                path=StringSchema(
                    "Path to the file to edit. Relative paths resolve against the "
                    "workspace; absolute paths and '..' obey the workspace access policy."
                ),
                action=StringSchema(
                    "replace updates a unique text match; add creates a file or appends to an existing one.",
                    enum=["replace", "add"],
                ),
                old_text=StringSchema(
                    "Exact text occurring once in the file; required for replace.",
                    nullable=True,
                ),
                new_text=StringSchema(
                    "Text to replace with or append. Required for replace and add.",
                    nullable=True,
                ),
                required=["path", "action"],
            ),
            description="File edits, applied in order.",
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
class ApplyPatchTool(_WritableFsTool):
    """Apply file edits by providing structured edit instructions."""
    _scopes = {"core", "subagent"}

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "Default tool for code edits, including multi-file changes. "
            "Returns a file-change summary. "
            "Use edit_file only for small exact replacements on a single file."
        )

    def _file_edit_paths(self, params: Mapping[str, object]) -> Iterator[str]:
        edits = params.get("edits")
        if params.get("dry_run") is True or not isinstance(edits, list):
            return
        for edit in cast(list[object], edits):
            if isinstance(edit, dict):
                try:
                    yield _validate_patch_path(cast(dict[str, object], edit).get("path"))
                except _PatchError:
                    continue

    async def execute(
        self,
        edits: list[object] | None = None,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            if not edits:
                raise _PatchError("must provide edits")

            writes: dict[WritableFile, str] = {}
            originals: dict[WritableFile, str] = {}
            actions: dict[WritableFile, str] = {}

            for edit_value in edits:
                if not isinstance(edit_value, dict):
                    raise _PatchError("each edit must be an object")
                edit = cast(dict[str, Any], edit_value)
                path = _validate_patch_path(edit.get("path"))
                action = edit.get("action")
                if not isinstance(action, str):
                    raise _PatchError(f"action required for edit: {path}")
                source = self._files.edit_target(path)
                if action not in ("add", "replace"):
                    raise _PatchError(f"unknown action: {action}")
                old_text = edit.get("old_text") or ""
                if action == "replace" and not old_text:
                    raise _PatchError(f"old_text required for replace: {path}")
                new_text = edit.get("new_text")
                if new_text is None:
                    raise _PatchError(f"new_text required for {action}: {path}")
                new_text = cast(str, new_text)

                pending = writes.get(source)
                content = pending
                if content is None and source.exists():
                    try:
                        content = source.read_bytes().decode("utf-8")
                    except UnicodeDecodeError:
                        raise _PatchError(f"file is not UTF-8 text: {path}")
                created = content is None
                if content is None:
                    if action == "replace":
                        raise _PatchError(f"file to update does not exist: {path}")
                    content = ""

                if action == "replace" and pending is None and not source.is_file():
                    raise _PatchError(f"path to update is not a file: {path}")

                norm_content = content.replace("\r\n", "\n")
                if action == "add":
                    norm_new = new_text.replace("\r\n", "\n")
                    if norm_content and norm_new and not norm_content.endswith("\n") and not norm_new.startswith("\n"):
                        norm_content += "\n"
                    updated = norm_content + norm_new
                else:
                    norm_old = cast(str, old_text).replace("\r\n", "\n")

                    pos = norm_content.find(norm_old)
                    if pos < 0:
                        raise _PatchError(f"old_text not found in {path}")
                    if norm_content.find(norm_old, pos + 1) >= 0:
                        raise _PatchError(f"old_text appears multiple times in {path}")

                    updated = (
                        norm_content[:pos]
                        + new_text.replace("\r\n", "\n")
                        + norm_content[pos + len(norm_old) :]
                    )

                if updated and not updated.endswith("\n"):
                    updated += "\n"
                writes[source] = updated.replace("\n", "\r\n") if "\r\n" in content else updated
                originals.setdefault(source, content)
                actions.setdefault(source, "add" if created else "update")

            diffs = {
                source: FileDiff.from_text(originals[source], content)
                for source, content in writes.items()
            }
            summaries: list[str] = []
            for source, diff in diffs.items():
                action_name = actions[source]
                path = display_file_edit_path(source.path, self._files.display_workspace)
                added, deleted = diff.added, diff.deleted
                stats = f" (+{added}/-{deleted})" if added or deleted else ""
                summaries.append(f"- {action_name} {path}{stats}")

            if dry_run:
                return "Patch dry-run succeeded:\n" + "\n".join(summaries)

            commit_file_edits(writes)
            for target in writes:
                self._file_states.record_write(target.path)
            return FileEditResult(
                "Patch applied:\n" + "\n".join(summaries),
                {target.path: diff for target, diff in diffs.items()},
            )
        except PermissionError as exc:
            return ToolResult.error(f"Error: {exc}")
        except _PatchError as exc:
            return ToolResult.error(f"Error applying patch: {exc}")
        except Exception as exc:
            return ToolResult.error(f"Error applying patch: {exc}")
