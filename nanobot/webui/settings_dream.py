"""Settings access to the default workspace Dream prompt."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.config.loader import load_config
from nanobot.config.schema import Config
from nanobot.utils.workspace_prompts import WORKSPACE_PROMPT_MAX_CHARS, workspace_prompt_file
from nanobot.webui.settings_contracts import WebUISettingsError


def dream_prompt_payload(config: Config) -> dict[str, Any]:
    path = workspace_prompt_file(config.workspace_path, "dream")
    default = MemoryStore.default_dream_prompt()
    try:
        if path.parent.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(config.workspace_path.resolve()):
            raise OSError("Prompt is outside the workspace")
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""
    except (OSError, UnicodeError):
        return {"content": default, "default_content": default, "custom": False,
                "workspace": str(config.workspace_path), "editable": False}
    return {"content": content if content.strip() else default, "default_content": default,
            "custom": bool(content.strip()), "workspace": str(config.workspace_path),
            "editable": True}


def update_dream_prompt(content: Any, *, config_path: Path | None = None) -> dict[str, Any]:
    if content is not None and (not isinstance(content, str) or not content.strip()
                                or len(content) > WORKSPACE_PROMPT_MAX_CHARS):
        raise WebUISettingsError("Dream prompt must contain 1–32000 characters")
    config = load_config(config_path)
    workspace = config.workspace_path.resolve()
    path = workspace_prompt_file(workspace, "dream")
    if path.parent.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(workspace):
        raise WebUISettingsError("Dream prompt must stay inside the default workspace")
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as stream:
            temporary = stream.name
            stream.write(content if content is not None else "")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise WebUISettingsError(f"Could not save Dream prompt: {exc}") from exc
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
    return dream_prompt_payload(config)
