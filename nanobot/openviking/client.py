"""VikingClient — async wrapper around the OpenViking SDK."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from loguru import logger

try:
    import openviking as ov
    from openviking.message.part import Part, TextPart, ToolPart

    HAS_OPENVIKING = True
except Exception:
    HAS_OPENVIKING = False
    ov = None  # type: ignore[assignment]


class VikingClient:
    """Async client wrapping the OpenViking SDK for local or remote mode."""

    def __init__(
        self,
        *,
        mode: str = "local",
        data_dir: str = "",
        server_url: str = "",
        api_key: str = "",
        user_id: str = "",
        agent_id: str | None = None,
        vlm_api_key: str = "",
        vlm_base_url: str = "",
        vlm_model: str = "",
        embedding_model: str = "",
        embedding_api_key: str = "",
        embedding_base_url: str = "",
    ):
        if not HAS_OPENVIKING:
            raise RuntimeError("openviking package is not installed. Install with: pip install openviking")

        self.mode = mode
        self.user_id = user_id or "default"
        self.agent_id = agent_id or "default"

        if mode == "local":
            ov_data_path = Path(data_dir).expanduser()
            ov_data_path.mkdir(parents=True, exist_ok=True)

            init_kwargs: dict[str, Any] = {"path": str(ov_data_path)}
            if vlm_api_key and vlm_base_url and vlm_model:
                init_kwargs["vlm"] = {
                    "api_key": vlm_api_key,
                    "base_url": vlm_base_url,
                    "model": vlm_model,
                }
            if embedding_model and embedding_api_key and embedding_base_url:
                init_kwargs["embedding"] = {
                    "model": embedding_model,
                    "api_key": embedding_api_key,
                    "base_url": embedding_base_url,
                }

            self.client = ov.AsyncOpenViking(**init_kwargs)
            self.agent_space_name = self.client.user.agent_space_name()
        else:
            self.client = ov.AsyncHTTPClient(
                url=server_url,
                api_key=api_key,
                agent_id=agent_id,
            )
            self.agent_space_name = hashlib.md5(
                (self.user_id + (agent_id or "")).encode()
            ).hexdigest()[:12]

    async def _initialize(self) -> None:
        await self.client.initialize()

    @classmethod
    async def create(
        cls,
        *,
        mode: str = "local",
        data_dir: str = "",
        server_url: str = "",
        api_key: str = "",
        user_id: str = "",
        agent_id: str | None = None,
        vlm_api_key: str = "",
        vlm_base_url: str = "",
        vlm_model: str = "",
        embedding_model: str = "",
        embedding_api_key: str = "",
        embedding_base_url: str = "",
    ) -> "VikingClient":
        """Factory: create and initialise a VikingClient."""
        instance = cls(
            mode=mode,
            data_dir=data_dir,
            server_url=server_url,
            api_key=api_key,
            user_id=user_id,
            agent_id=agent_id,
            vlm_api_key=vlm_api_key,
            vlm_base_url=vlm_base_url,
            vlm_model=vlm_model,
            embedding_model=embedding_model,
            embedding_api_key=embedding_api_key,
            embedding_base_url=embedding_base_url,
        )
        await instance._initialize()
        return instance

    @classmethod
    async def from_config(cls, agent_id: str | None = None) -> "VikingClient":
        """Create a VikingClient from the global nanobot config."""
        from nanobot.config.loader import load_config

        cfg = load_config().openviking
        return await cls.create(
            mode=cfg.mode,
            data_dir=cfg.data_dir,
            server_url=cfg.server_url,
            api_key=cfg.api_key,
            user_id=cfg.user_id,
            agent_id=agent_id,
            vlm_api_key=cfg.vlm_api_key,
            vlm_base_url=cfg.vlm_base_url,
            vlm_model=cfg.vlm_model,
            embedding_model=cfg.embedding_model,
            embedding_api_key=cfg.embedding_api_key,
            embedding_base_url=cfg.embedding_base_url,
        )

    # ------------------------------------------------------------------
    # Search & find
    # ------------------------------------------------------------------

    async def find(self, query: str, target_uri: str | None = None, limit: int = 10) -> Any:
        if target_uri:
            return await self.client.find(query, target_uri=target_uri, limit=limit)
        return await self.client.find(query, limit=limit)

    async def search(self, query: str, target_uri: str = "") -> dict[str, Any]:
        result = await self.client.search(query, target_uri=target_uri)
        return {
            "memories": [self._matched_to_dict(m) for m in getattr(result, "memories", [])],
            "resources": [self._matched_to_dict(r) for r in getattr(result, "resources", [])],
            "skills": [self._matched_to_dict(s) for s in getattr(result, "skills", [])],
            "total": getattr(result, "total", 0),
            "query": query,
            "target_uri": target_uri,
        }

    async def search_user_memory(self, query: str) -> list[dict[str, Any]]:
        uri = f"viking://user/{self.user_id}/memories/"
        result = await self.client.search(query, target_uri=uri)
        return [self._matched_to_dict(m) for m in getattr(result, "memories", [])]

    async def search_memory(self, query: str, limit: int = 10) -> dict[str, list[Any]]:
        """Search both user and agent memories."""
        uri_user = f"viking://user/{self.user_id}/memories/"
        user_result = await self.client.find(query=query, target_uri=uri_user, limit=limit)

        uri_agent = f"viking://agent/{self.agent_space_name}/memories/"
        agent_result = await self.client.find(query=query, target_uri=uri_agent, limit=limit)

        return {
            "user_memory": getattr(user_result, "memories", []),
            "agent_memory": getattr(agent_result, "memories", []),
        }

    # ------------------------------------------------------------------
    # Resource management
    # ------------------------------------------------------------------

    async def add_resource(
        self, local_path: str, desc: str, wait: bool = False,
    ) -> dict[str, Any] | None:
        result = await self.client.add_resource(path=local_path, reason=desc, wait=wait)
        return result

    async def list_resources(self, path: str | None = None, recursive: bool = False) -> list:
        if not path:
            path = "viking://resources/"
        return await self.client.ls(path, recursive=recursive)

    async def read_content(self, uri: str, level: str = "abstract") -> str:
        try:
            if level == "abstract":
                return await self.client.abstract(uri)
            elif level == "overview":
                return await self.client.overview(uri)
            elif level == "read":
                return await self.client.read(uri)
            else:
                raise ValueError(f"Unsupported level: {level}")
        except FileNotFoundError:
            return ""
        except Exception as e:
            logger.warning("Failed to read content from {}: {}", uri, e)
            return ""

    async def grep(self, uri: str, pattern: str, case_insensitive: bool = False) -> Any:
        return await self.client.grep(uri, pattern, case_insensitive=case_insensitive)

    async def glob(self, pattern: str, uri: str | None = None) -> Any:
        return await self.client.glob(pattern, uri=uri)

    # ------------------------------------------------------------------
    # Session commit
    # ------------------------------------------------------------------

    async def commit(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Commit conversation messages to OpenViking."""
        session = self.client.session(session_id)

        if self.mode == "local":
            for message in messages:
                role = message.get("role")
                content = message.get("content")
                tools_used = message.get("tools_used") or []

                parts: list[Part] = []
                if content:
                    parts.append(TextPart(text=content))

                for tool_info in tools_used:
                    tool_name = tool_info.get("tool_name", "")
                    if not tool_name:
                        continue

                    tool_id = f"{tool_name}_{uuid.uuid4().hex[:8]}"
                    try:
                        import json
                        args_str = tool_info.get("args", "{}")
                        tool_input = json.loads(args_str) if args_str else {}
                    except Exception:
                        tool_input = {"raw_args": tool_info.get("args", "")}

                    result_str = str(tool_info.get("result", ""))
                    skill_uri = ""
                    if tool_name == "read_file" and result_str:
                        match = re.search(r"^---\s*\nname:\s*(.+?)\s*\n", result_str, re.MULTILINE)
                        if match:
                            skill_uri = f"viking://agent/skills/{match.group(1).strip()}"

                    execute_success = tool_info.get("execute_success", True)
                    parts.append(
                        ToolPart(
                            tool_id=tool_id,
                            tool_name=tool_name,
                            tool_uri=f"viking://session/{session_id}/tools/{tool_id}",
                            tool_input=tool_input,
                            tool_output=result_str[:2000],
                            tool_status="completed" if execute_success else "error",
                            skill_uri=skill_uri,
                            duration_ms=float(tool_info.get("duration", 0.0)),
                            prompt_tokens=tool_info.get("input_token"),
                            completion_tokens=tool_info.get("output_token"),
                        )
                    )

                if not parts:
                    parts = [TextPart(text=content or "")]
                session.add_message(role=role, parts=parts)

            result = session.commit()
        else:
            for message in messages:
                await session.add_message(role=message.get("role"), content=message.get("content"))
            result = await session.commit()

        logger.debug("Committed {} messages to OpenViking session {}", len(messages), session_id)
        return {"success": result.get("status", False)}

    # ------------------------------------------------------------------
    # Memory context helpers
    # ------------------------------------------------------------------

    async def get_viking_memory_context(self, current_message: str) -> str:
        """Return formatted Viking memory context for the system prompt."""
        result = await self.search_memory(current_message, limit=5)
        if not result:
            return ""
        user_text = self._format_memories(result.get("user_memory", []))
        agent_text = self._format_memories(result.get("agent_memory", []))
        if not user_text and not agent_text:
            return ""
        return (
            "## Related Memories (use tools for details)\n"
            f"### User Memories\n{user_text or '(none)'}\n"
            f"### Agent Memories\n{agent_text or '(none)'}"
        )

    async def get_viking_user_profile(self) -> str:
        content = await self.read_content(
            uri=f"viking://user/{self.user_id}/memories/profile.md", level="read"
        )
        if not content:
            return ""
        return f"## User Profile\n{content}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _matched_to_dict(ctx: Any) -> dict[str, Any]:
        return {
            "uri": getattr(ctx, "uri", ""),
            "context_type": str(getattr(ctx, "context_type", "")),
            "is_leaf": getattr(ctx, "is_leaf", False),
            "abstract": getattr(ctx, "abstract", ""),
            "overview": getattr(ctx, "overview", None),
            "category": getattr(ctx, "category", ""),
            "score": getattr(ctx, "score", 0.0),
            "match_reason": getattr(ctx, "match_reason", ""),
        }

    @staticmethod
    def _format_memories(memories: list) -> str:
        if not memories:
            return ""
        lines = []
        for idx, m in enumerate(memories, 1):
            abstract = getattr(m, "abstract", "")
            uri = getattr(m, "uri", "")
            score = getattr(m, "score", 0.0)
            lines.append(f"{idx}. {abstract}; uri: {uri}; score: {score:.2f}")
        return "\n".join(lines)

    def close(self) -> None:
        self.client.close()
