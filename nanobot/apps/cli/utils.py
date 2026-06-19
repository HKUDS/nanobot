"""CLI Apps helpers shared by the agent loop and settings surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def session_extra(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return persisted session kwargs for CLI app attachments."""
    cli_apps = metadata.get("cli_apps") if isinstance(metadata, Mapping) else None
    return {"cli_apps": cli_apps} if isinstance(cli_apps, list) and cli_apps else {}


def runtime_lines(message: Any, workspace: Path, *, skip: bool = False) -> list[str]:
    """Return model-visible CLI app annotations for the current turn."""
    if skip:
        return []
    text = message.content if isinstance(getattr(message, "content", None), str) else ""
    metadata = message.metadata if isinstance(getattr(message, "metadata", None), Mapping) else None
    return _cli_app_runtime_lines(text, metadata, workspace)


def _cli_app_runtime_lines(
    text: str,
    metadata: Mapping[str, Any] | None,
    workspace: Path,
) -> list[str]:
    structured = metadata.get("cli_apps") if isinstance(metadata, Mapping) else None
    if isinstance(structured, list):
        mentions = [
            item for item in structured
            if isinstance(item, Mapping) and isinstance(item.get("name"), str)
        ]
        if mentions:
            return [
                "CLI App Attachment: "
                f"@{str(item['name']).strip().lower()} "
                f"(installed; tool=run_cli_app; "
                f"entry_point={str(item.get('entry_point') or 'unknown')}; "
                f"skill=skills/cli-app-{str(item['name']).strip().lower()}/SKILL.md). "
                "Read the skill when useful, then run this app with `run_cli_app`; do not bypass it with shell."
                for item in mentions
                if str(item.get("name") or "").strip()
            ]
    if "@" not in text:
        return []
    try:
        from nanobot.apps.cli import CliAppManager

        mentions = CliAppManager(workspace=workspace).mentioned_installed_apps(text)
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
