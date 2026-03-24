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

        if event == HookEvent.PRE_BUILD_CONTEXT:
            env["CONTEXT_TYPE"] = context.get("type", "")
            env["CHANNEL"] = context.get("channel", "")
            env["CHAT_ID"] = context.get("chat_id", "")

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

            # For prompt_injection events, capture stdout as injected content
            if (
                result.returncode == 0
                and event == HookEvent.PRE_BUILD_CONTEXT
                and context.get("type") == "prompt_injection"
            ):
                stdout = result.stdout.strip()
                if stdout:
                    return HookResult(modified_data=stdout)

            return HookResult()

        except subprocess.TimeoutExpired:
            logger.error("Hook '{}' timed out after 30s", self._name)
            return HookResult()
        except Exception as e:
            logger.exception("Hook '{}' failed: {}", self._name, e)
            return HookResult()


def validate_hook_config(hook_config: dict) -> tuple[bool, str]:
    """Validate a single hook configuration.

    Returns:
        (is_valid, error_message)
    """
    required_fields = ["name", "event", "command"]
    for field in required_fields:
        if field not in hook_config:
            return False, f"Missing required field: {field}"

    # Validate event name
    try:
        HookEvent(hook_config["event"])
    except ValueError:
        valid_events = [e.value for e in HookEvent]
        return False, f"Invalid event '{hook_config['event']}'. Valid events: {', '.join(valid_events)}"

    # Validate priority if present
    if "priority" in hook_config:
        if not isinstance(hook_config["priority"], int):
            return False, "Priority must be an integer"

    # Validate matcher if present
    if "matcher" in hook_config:
        try:
            import re
            re.compile(hook_config["matcher"])
        except re.error as e:
            return False, f"Invalid matcher regex: {e}"

    return True, ""


def load_hooks_from_json(workspace: Path, validate_only: bool = False) -> list[Hook]:
    """Load user-defined hooks from workspace/.nanobot/hooks.json.

    Args:
        workspace: Workspace directory
        validate_only: If True, only validate without creating hook instances

    Returns:
        List of JsonConfigHook instances (empty if validate_only=True).
    """
    hooks_file = workspace / ".nanobot" / "hooks.json"
    if not hooks_file.exists():
        return []

    try:
        config = json.loads(hooks_file.read_text(encoding="utf-8"))
        hooks = []
        validation_errors = []

        for hook_config in config.get("hooks", []):
            hook_name = hook_config.get("name", "unknown")

            # Validate configuration
            is_valid, error_msg = validate_hook_config(hook_config)
            if not is_valid:
                validation_errors.append(f"Hook '{hook_name}': {error_msg}")
                continue

            if validate_only:
                logger.debug("Validated hook: {}", hook_name)
                continue

            try:
                hooks.append(JsonConfigHook(hook_config))
                logger.debug("Loaded user hook: {}", hook_name)
            except Exception as e:
                logger.error("Failed to load hook {}: {}", hook_name, e)

        if validation_errors:
            logger.error("Hook validation errors:\n{}", "\n".join(validation_errors))

        return hooks
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in hooks.json: {}", e)
        return []
    except Exception as e:
        logger.error("Failed to load hooks.json: {}", e)
        return []
