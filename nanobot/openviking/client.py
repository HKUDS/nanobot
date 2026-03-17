"""VikingClient — async wrapper around the OpenViking SDK."""

from __future__ import annotations

import asyncio
import time
import hashlib
import json
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
        embedding_dimension: int = 1024,
        min_recall_score: float = 0.5,
    ):
        if not HAS_OPENVIKING:
            raise RuntimeError("openviking package is not installed. Install with: pip install openviking")

        self.mode = mode
        self.user_id = user_id or "default"
        self.agent_id = agent_id or "default"

        if mode == "local":
            ov_data_path = Path(data_dir).expanduser()
            ov_data_path.mkdir(parents=True, exist_ok=True)

            self._ensure_ov_config(
                str(ov_data_path),
                embedding_model=embedding_model,
                embedding_api_key=embedding_api_key,
                embedding_base_url=embedding_base_url,
                embedding_dimension=embedding_dimension,
                vlm_api_key=vlm_api_key,
                vlm_base_url=vlm_base_url,
                vlm_model=vlm_model,
            )

            self.client = ov.AsyncOpenViking(path=str(ov_data_path))
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

        self._commit_semaphore = asyncio.Semaphore(1)
        self.min_recall_score = min_recall_score

    def set_max_concurrent_commits(self, n: int) -> None:
        """Update the concurrency limit for commit operations."""
        self._commit_semaphore = asyncio.Semaphore(max(1, n))

    @staticmethod
    def _ensure_ov_config(
        workspace: str,
        *,
        embedding_model: str,
        embedding_api_key: str,
        embedding_base_url: str,
        embedding_dimension: int,
        vlm_api_key: str,
        vlm_base_url: str,
        vlm_model: str,
    ) -> None:
        """Pre-seed the OpenViking config singleton so ov.conf is not required.

        If a config file (``~/.openviking/ov.conf`` or ``$OPENVIKING_CONFIG_FILE``)
        already exists the SDK will load it normally. This method only kicks in
        when no file is found, building the config dict from the parameters that
        nanobot already knows about and injecting it via the SDK singleton.
        """
        try:
            from openviking_cli.utils.config import (
                OpenVikingConfigSingleton,
                resolve_config_path,
                DEFAULT_OV_CONF,
                OPENVIKING_CONFIG_ENV,
            )
        except ImportError:
            return

        existing = resolve_config_path(None, OPENVIKING_CONFIG_ENV, DEFAULT_OV_CONF)
        if existing is not None:
            return

        config_dict: dict[str, Any] = {
            "storage": {"workspace": workspace},
        }

        if embedding_model and embedding_api_key and embedding_base_url:
            config_dict["embedding"] = {
                "dense": {
                    "provider": "openai",
                    "model": embedding_model,
                    "api_key": embedding_api_key,
                    "api_base": embedding_base_url,
                    "dimension": embedding_dimension,
                    "batch_size": 32,
                }
            }

        if vlm_api_key and vlm_base_url and vlm_model:
            config_dict["vlm"] = {
                "provider": "openai",
                "model": vlm_model,
                "api_key": vlm_api_key,
                "api_base": vlm_base_url,
            }

        OpenVikingConfigSingleton.initialize(config_dict=config_dict)
        logger.info("OpenViking config bootstrapped from nanobot parameters (no ov.conf)")

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
        embedding_dimension: int = 1024,
        min_recall_score: float = 0.5,
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
            embedding_dimension=embedding_dimension,
            min_recall_score=min_recall_score,
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
            embedding_dimension=cfg.embedding_dimension,
            min_recall_score=getattr(cfg, "min_recall_score", 0.5),
        )

    # ------------------------------------------------------------------
    # User management (remote mode)
    # ------------------------------------------------------------------

    async def _check_user_exists(self, user_id: str) -> bool:
        """Check whether a user exists. Always True for local mode."""
        if self.mode == "local":
            return True
        try:
            from nanobot.config.loader import load_config
            cfg = load_config().openviking
            account_id = getattr(cfg, "account_id", "") or "default"
            res = await self.client.admin_list_users(account_id)
            if not res:
                return False
            return any(u.get("user_id") == user_id for u in res)
        except Exception as e:
            logger.warning("Failed to check user existence: {}", e)
            return False

    async def _initialize_user(self, user_id: str, role: str = "user") -> bool:
        """Register a user in the remote account. No-op for local mode."""
        if self.mode == "local":
            return True
        try:
            from nanobot.config.loader import load_config
            cfg = load_config().openviking
            account_id = getattr(cfg, "account_id", "") or "default"
            await self.client.admin_register_user(
                account_id=account_id, user_id=user_id, role=role,
            )
            return True
        except Exception as e:
            if "User already exists" in str(e):
                return True
            logger.warning("Failed to initialize user {}: {}", user_id, e)
            return False

    async def _ensure_user(self, user_id: str) -> bool:
        """Check and auto-initialize a user if needed. Returns success."""
        if self.mode == "local" or not user_id:
            return True
        if await self._check_user_exists(user_id):
            return True
        return await self._initialize_user(user_id)

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

    async def search_user_memory(self, query: str, sender_id: str = "") -> list[dict[str, Any]]:
        uid = sender_id or self.user_id
        if not await self._ensure_user(uid):
            return []
        uri = f"viking://user/{uid}/memories/"
        result = await self.client.search(query, target_uri=uri)
        return [self._matched_to_dict(m) for m in getattr(result, "memories", [])]

    async def search_memory(self, query: str, limit: int = 10) -> dict[str, list[Any]]:
        """Search both user and agent memories."""
        if not await self._ensure_user(self.user_id):
            return {"user_memory": [], "agent_memory": []}

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
        self, local_path: str, desc: str, target_path: str = "", wait: bool = False,
    ) -> dict[str, Any] | None:
        result = await self.client.add_resource(
            path=local_path, reason=desc, target_path=target_path or None, wait=wait,
        )
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

    async def grep(
        self,
        uri: str,
        pattern: str,
        case_insensitive: bool = False,
        node_limit: int = 10,
    ) -> Any:
        try:
            return await self.client.grep(
                uri, pattern, case_insensitive=case_insensitive, node_limit=node_limit
            )
        except TypeError:
            return await self.client.grep(uri, pattern, case_insensitive=case_insensitive)

    async def glob(self, pattern: str, uri: str | None = None) -> Any:
        return await self.client.glob(pattern, uri=uri)

    # ------------------------------------------------------------------
    # Session commit
    # ------------------------------------------------------------------

    _COMMIT_BATCH_SIZE = 100

    async def commit(
        self, session_id: str, messages: list[dict[str, Any]], sender_id: str = "",
    ) -> dict[str, Any]:
        """Commit conversation messages to OpenViking.

        Large message lists are automatically split into batches to avoid
        exceeding the LLM token limit during memory extraction.  The
        semaphore limits concurrent commits to control memory usage, and
        ``session.commit()`` is offloaded to a thread to avoid blocking
        the event loop.
        """
        if len(messages) > self._COMMIT_BATCH_SIZE:
            logger.info(
                "Splitting {} messages into batches of {}",
                len(messages), self._COMMIT_BATCH_SIZE,
            )
            all_ok = True
            for i in range(0, len(messages), self._COMMIT_BATCH_SIZE):
                batch = messages[i : i + self._COMMIT_BATCH_SIZE]
                result = await self._commit_batch(session_id, batch, sender_id)
                if not result.get("success"):
                    all_ok = False
            return {"success": all_ok}

        return await self._commit_batch(session_id, messages, sender_id)

    async def _commit_batch(
        self, session_id: str, messages: list[dict[str, Any]], sender_id: str = "",
    ) -> dict[str, Any]:
        """Commit a single batch of messages (at most ``_COMMIT_BATCH_SIZE``)."""
        async with self._commit_semaphore:
            uid = sender_id or self.user_id
            if not await self._ensure_user(uid):
                return {"success": False, "error": "Failed to initialize user"}

            actual_sid = session_id
            if hasattr(self.client, "create_session"):
                try:
                    res = await self.client.create_session()
                    actual_sid = res["session_id"]
                except Exception:
                    logger.debug("create_session unavailable, falling back to provided session_id")

            session = self.client.session(actual_sid)

            for message in messages:
                role = message.get("role")
                content = message.get("content")
                tools_used = message.get("tools_used") or []

                parts: list[Part] = []
                if content:
                    parts.append(TextPart(text=self._normalize_content(content)))

                for tool_info in tools_used:
                    tool_name = tool_info.get("tool_name", "")
                    if not tool_name:
                        continue

                    tool_id = f"{tool_name}_{uuid.uuid4().hex[:8]}"
                    try:
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
                            tool_uri=f"viking://session/{actual_sid}/tools/{tool_id}",
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
                    continue
                session.add_message(role=role, parts=parts)

            result = await asyncio.to_thread(session.commit)
            logger.debug("Committed {} messages to OpenViking session {}", len(messages), actual_sid)
            status = result.get("status", False)
            return {"success": status is True or status == "committed"}

    # ------------------------------------------------------------------
    # Memory context helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_schema_uri(uri: str) -> bool:
        """Exclude structural metadata (overview/abstract) from recall."""
        parts = uri.rstrip("/").split("/")
        last = parts[-1] if parts else ""
        return last in (".overview.md", ".abstract.md")

    @staticmethod
    def _filter_recall_results(
        user_memory: list, agent_memory: list, min_recall_score: float
    ) -> tuple[list, list]:
        """Filter by min_recall_score and exclude schema URIs."""
        def keep(m):
            uri = getattr(m, "uri", "") or ""
            score = getattr(m, "score", 0.0)
            return score >= min_recall_score and not VikingClient._is_schema_uri(uri)

        return (
            [m for m in (user_memory or []) if keep(m)],
            [m for m in (agent_memory or []) if keep(m)],
        )

    async def get_viking_memory_context(self, current_message: str) -> str:
        """Return formatted Viking memory context for the system prompt.

        Only injects memories when:
        - Top score >= min_recall_score (avoids low-relevance noise)
        - URI is not schema/overview (.overview.md, .abstract.md)
        """
        start = time.perf_counter()
        result = await self.search_memory(current_message, limit=5)
        if not result:
            logger.debug("[READ_USER_MEMORY]: cost {:.2f}s, search failed", time.perf_counter() - start)
            return ""
        user_raw = result.get("user_memory", [])
        agent_raw = result.get("agent_memory", [])
        user_memory, agent_memory = self._filter_recall_results(
            user_raw, agent_raw, self.min_recall_score
        )
        if not user_memory and not agent_memory:
            logger.debug(
                "[READ_USER_MEMORY]: cost {:.2f}s, no matches",
                time.perf_counter() - start,
            )
            return ""
        user_text = self._format_memories(user_memory)
        agent_text = self._format_memories(agent_memory)
        if not user_text and not agent_text:
            return ""
        cost = time.perf_counter() - start
        logger.info("[READ_USER_MEMORY]: cost {:.2f}s, user={}, agent={}", cost, len(user_memory), len(agent_memory))
        return (
            "## Related Memories (use tools for details)\n"
            f"### User Memories\n{user_text or '(none)'}\n"
            f"### Agent Memories\n{agent_text or '(none)'}"
        )

    async def get_viking_user_profile(self) -> str:
        start = time.perf_counter()
        if not await self._ensure_user(self.user_id):
            return ""
        content = await self.read_content(
            uri=f"viking://user/{self.user_id}/memories/profile.md", level="read"
        )
        cost = time.perf_counter() - start
        logger.info("[READ_USER_PROFILE]: cost {:.2f}s, profile={}", cost, "yes" if content else "none")
        if not content:
            return ""
        return f"## User Profile\n{content}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_content(content: Any) -> str:
        """Flatten multimodal content lists into a plain string.

        LLM messages may carry ``content`` as a list of dicts
        (e.g. ``[{"type": "text", "text": "..."}, {"type": "image_url", ...}]``)
        when images are involved.  OpenViking's ``TextPart`` expects a plain
        string, so we extract and join all text segments here.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    t = part.get("text") or part.get("content") or ""
                    if isinstance(t, str) and t:
                        texts.append(t)
                elif isinstance(part, str):
                    texts.append(part)
            return "\n".join(texts) if texts else str(content)
        return str(content)

    @staticmethod
    def _relation_to_dict(rel: Any) -> dict[str, Any]:
        return {
            "from_uri": getattr(rel, "from_uri", ""),
            "to_uri": getattr(rel, "to_uri", ""),
            "relation_type": getattr(rel, "relation_type", ""),
            "reason": getattr(rel, "reason", ""),
        }

    @classmethod
    def _matched_to_dict(cls, ctx: Any) -> dict[str, Any]:
        return {
            "uri": getattr(ctx, "uri", ""),
            "context_type": str(getattr(ctx, "context_type", "")),
            "is_leaf": getattr(ctx, "is_leaf", False),
            "abstract": getattr(ctx, "abstract", ""),
            "overview": getattr(ctx, "overview", None),
            "category": getattr(ctx, "category", ""),
            "score": getattr(ctx, "score", 0.0),
            "match_reason": getattr(ctx, "match_reason", ""),
            "relations": [
                cls._relation_to_dict(r) for r in getattr(ctx, "relations", [])
            ],
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

    async def aclose(self) -> None:
        if hasattr(self.client, "close"):
            result = self.client.close()
            if hasattr(result, "__await__"):
                await result

    def close(self) -> None:
        if hasattr(self.client, "close"):
            self.client.close()
