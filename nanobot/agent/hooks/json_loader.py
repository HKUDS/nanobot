"""JSON-based hook loader for user-defined hooks."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from loguru import logger

from nanobot.agent.hooks.base import Hook, HookEvent, HookResult


class JsonConfigHook(Hook):
    """Hook loaded from JSON configuration that executes shell commands.

    Exit codes:
    - 0: Proceed (hook passes)
    - 2: Block (hook blocks execution)
    - Other: Treated as error, hook passes

    Environment variables passed to command:
    - HOOK_EVENT: Event name (e.g., "PreToolUse")
    - TOOL_NAME: Tool name (for tool events)
    - TOOL_ARGS: JSON-encoded tool arguments (for tool events)
    """

    def __init__(self, config: dict):
        self._name = config["name"]
        self._event = HookEvent(config["event"])
        self._matcher = config.get("matcher")
        self._command = config["command"]
        self._priority = config.get("priority", 100)

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def matcher(self) -> str | None:
        return self._matcher

    def on_event(self, event: HookEvent, context: dict) -> HookResult:
        if event != self._event:
            return HookResult()

        # Build environment variables
        env = {
            "HOOK_EVENT": event.value,
        }

        if event in (HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE):
            env["TOOL_NAME"] = context.get("tool_name", "")
            env["TOOL_ARGS"] = json.dumps(context.get("tool_args", {}))
            if event == HookEvent.POST_TOOL_USE:
                env["TOOL_RESULT"] = str(context.get("result", ""))

        try:
            result = subprocess.run(
                self._command,
                shell=True,
                capture_output=True,
                text=True,
                env={**os.environ, **env},
                timeout=30,
            )

            if result.returncode == 2:
                reason = result.stdout.strip() or "Hook blocked execution"
                logger.info("Hook '{}' blocked: {}", self._name, reason)
                return HookResult(proceed=False, reason=reason)

            if result.returncode != 0:
                logger.warning(
                    "Hook '{}' exited with code {} (treating as pass): {}",
                    self._name,
                    result.returncode,
                    result.stderr.strip(),
                )

            return HookResult()

        except subprocess.TimeoutExpired:
            logger.error("Hook '{}' timed out after 30s", self._name)
            return HookResult()
        except Exception as e:
            logger.exception("Hook '{}' failed: {}", self._name, e)
            return HookResult()


def load_hooks_from_json(workspace: Path) -> list[Hook]:
    """Load user-defined hooks from workspace/.nanobot/hooks.json.

    Returns:
        List of JsonConfigHook instances.
    """
    hooks_file = workspace / ".nanobot" / "hooks.json"
    if not hooks_file.exists():
        return []

    try:
        config = json.loads(hooks_file.read_text(encoding="utf-8"))
        hooks = []

        for hook_config in config.get("hooks", []):
            try:
                hooks.append(JsonConfigHook(hook_config))
                logger.debug("Loaded user hook: {}", hook_config["name"])
            except Exception as e:
                logger.error("Failed to load hook {}: {}", hook_config.get("name", "unknown"), e)

        return hooks
    except Exception as e:
        logger.error("Failed to load hooks.json: {}", e)
        return []
