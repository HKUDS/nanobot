"""OpenViking hooks for memory commit and skill memory injection."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from nanobot.hooks.base import Hook, HookContext

try:
    from nanobot.openviking.client import VikingClient

    HAS_OPENVIKING = True
except Exception:
    HAS_OPENVIKING = False
    VikingClient = None  # type: ignore[assignment,misc]


class OpenVikingCompactHook(Hook):
    """On message.compact: commit session messages to OpenViking."""

    name = "openviking_compact"

    def __init__(self) -> None:
        self._client: VikingClient | None = None

    def set_client(self, client: VikingClient) -> None:
        self._client = client

    async def _get_client(self) -> VikingClient:
        if self._client is None:
            self._client = await VikingClient.from_config()
        return self._client

    async def execute(self, context: HookContext, **kwargs: Any) -> Any:
        session = kwargs.get("session")
        if not session or not hasattr(session, "messages"):
            return {"success": False, "error": "no session"}

        messages = session.messages
        if not messages:
            return {"success": True, "message": "no messages to commit"}

        try:
            client = await self._get_client()
            session_id = context.session_id or context.session_key or "default"
            sender_id = context.sender_id or ""
            result = await client.commit(session_id, messages, sender_id=sender_id)
            return result
        except Exception as e:
            logger.exception("OpenViking compact hook failed")
            return {"success": False, "error": str(e)}


class OpenVikingPostCallHook(Hook):
    """On tool.post_call: inject skill memory from OpenViking when a SKILL.md is read."""

    name = "openviking_post_call"

    def __init__(self) -> None:
        self._client: VikingClient | None = None

    def set_client(self, client: VikingClient) -> None:
        self._client = client

    async def _get_client(self) -> VikingClient:
        if self._client is None:
            self._client = await VikingClient.from_config()
        return self._client

    async def execute(self, context: HookContext, **kwargs: Any) -> Any:
        tool_name = kwargs.get("tool_name", "")
        result = kwargs.get("result", "")

        if tool_name != "read_file" or not result or isinstance(result, Exception):
            return {"tool_name": tool_name, "result": result}

        match = re.search(r"^---\s*\nname:\s*(.+?)\s*\n", result, re.MULTILINE)
        if not match:
            return {"tool_name": tool_name, "result": result}

        skill_name = match.group(1).strip()
        try:
            client = await self._get_client()
            skill_uri = f"viking://agent/{client.agent_space_name}/memories/skills/{skill_name}.md"
            content = await client.read_content(skill_uri, level="read")
            if content:
                result = f"{result}\n\n---\n## Skill Memory\n{content}"
        except Exception as e:
            logger.warning("Failed to read skill memory for {}: {}", skill_name, e)

        return {"tool_name": tool_name, "result": result}


def register_openviking_hooks(hook_manager: Any) -> None:
    """Register OpenViking hooks if the SDK is available."""
    if not HAS_OPENVIKING:
        logger.warning("OpenViking hooks requested but SDK not installed")
        return

    hook_manager.register("message.compact", OpenVikingCompactHook())
    hook_manager.register("tool.post_call", OpenVikingPostCallHook())
    logger.info("Registered OpenViking hooks (compact + post_call)")
