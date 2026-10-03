"""CLI Apps helpers shared by the agent loop and settings surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, cast


def session_extra(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return persisted session kwargs for CLI app attachments."""
    cli_apps = metadata.get("cli_apps") if isinstance(metadata, Mapping) else None
    return {"cli_apps": cli_apps} if isinstance(cli_apps, list) and cli_apps else {}


def runtime_lines_for_request(
    text: str,
    metadata: Mapping[str, Any] | None,
    workspace: Path,
) -> list[str]:
    """Return CLI App annotations from an immutable request snapshot."""
    structured = metadata.get("cli_apps") if isinstance(metadata, Mapping) else None
    if isinstance(structured, list):
        from nanobot.apps.cli.service import cli_app_skill_relative_path

        structured_items = cast(list[Any], structured)
        mentions = [
            cast(Mapping[str, Any], item) for item in structured_items
            if isinstance(item, Mapping)
            and isinstance(cast(Mapping[str, Any], item).get("name"), str)
        ]
        if mentions:
            return [
                "CLI App Attachment: "
                f"@{str(item['name']).strip().lower()} "
                f"(installed; tool=run_cli_app; "
                f"entry_point={str(item.get('entry_point') or 'unknown')}; "
                f"skill={cli_app_skill_relative_path(workspace, str(item['name']))}). "
                "Read the skill when useful, then run this app with `run_cli_app`; do not bypass it with shell."
                for item in mentions
                if str(item.get("name") or "").strip()
            ]
    if "@" not in text:
        return []
    try:
        from nanobot.apps.cli import CliAppManager

        mentions = cast(
            list[dict[str, Any]],
            CliAppManager(workspace=workspace).mentioned_installed_apps(text),
        )
    except Exception:
        return []
    return [
        "CLI App Mention: "
        f"@{item['name']} "
        f"(installed; tool={item['tool']}; "
        f"entry_point={item['entry_point'] or 'unknown'}; "
        f"skill={item['skill']}). "
        "Read the skill when useful, then run this app with `run_cli_app`; do not bypass it with shell."
        for item in mentions
    ]
