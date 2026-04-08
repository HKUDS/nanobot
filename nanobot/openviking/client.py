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
    from openviking_cli.session.user_id import UserIdentifier

    HAS_OPENVIKING = True
except Exception:
    HAS_OPENVIKING = False
    ov = None  # type: ignore[assignment]
    UserIdentifier = None  # type: ignore[assignment]


class VikingClient:
    """Async client wrapping the OpenViking SDK for local or remote mode."""

    def __init__(
        self,
        *,
        mode: str = "local",
        data_dir: str = "",
        server_url: str = "",
        api_key: str = "",
        account_id: str = "",
        user_id: str = "",
        agent_id: str | None = None,
        vlm_api_key: str = "",
        vlm_base_url: str = "",
        vlm_model: str = "",
        embedding_model: str = "",
        embedding_api_key: str = "",
        embedding_base_url: str = "",
        embedding_dimension: int = 1024,
        memory_recall_limit: int = 5,
    ):
        if not HAS_OPENVIKING:
            raise RuntimeError("openviking package is not installed. Install with: pip install openviking")

        self.mode = mode
        self.account_id = account_id or "default"
        self.user_id = user_id or "default"
        self.agent_id = agent_id or "default"
        self.memory_recall_limit = memory_recall_limit

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
            if self.user_id != "default" or self.agent_id != "default":
                logger.info(
                    "OpenViking local mode uses the SDK default user scope; configured user_id/agent_id are ignored"
                )
        else:
            self.client = ov.AsyncHTTPClient(
                url=server_url,
                api_key=api_key,
                user_id=self.user_id,
                agent_id=self.agent_id,
                account=self.account_id,
                user=self.user_id,
            )
            self.agent_space_name = self._derive_agent_space_name(
                account_id=self.account_id,
                user_id=self.user_id,
                agent_id=self.agent_id,
            )

        self._commit_semaphore = asyncio.Semaphore(1)

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

        if embedding_model and (embedding_api_key or embedding_base_url):
            config_dict["embedding"] = {
                "dense": {
                    "provider": "openai",
                    "model": embedding_model,
                    "api_key": embedding_api_key or None,
                    "api_base": embedding_base_url or None,
                    "dimension": embedding_dimension,
                    "batch_size": 32,
                }
            }
        else:
            raise RuntimeError(
                "OpenViking local mode on 0.3.3 requires embedding_model and embedding_api_key or embedding_base_url, "
                "unless an ov.conf file is already present."
            )

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
        account_id: str = "",
        user_id: str = "",
        agent_id: str | None = None,
        vlm_api_key: str = "",
        vlm_base_url: str = "",
        vlm_model: str = "",
        embedding_model: str = "",
        embedding_api_key: str = "",
        embedding_base_url: str = "",
        embedding_dimension: int = 1024,
        memory_recall_limit: int = 5,
    ) -> "VikingClient":
        """Factory: create and initialise a VikingClient."""
        instance = cls(
            mode=mode,
            data_dir=data_dir,
            server_url=server_url,
            api_key=api_key,
            account_id=account_id,
            user_id=user_id,
            agent_id=agent_id,
            vlm_api_key=vlm_api_key,
            vlm_base_url=vlm_base_url,
            vlm_model=vlm_model,
            embedding_model=embedding_model,
            embedding_api_key=embedding_api_key,
            embedding_base_url=embedding_base_url,
            embedding_dimension=embedding_dimension,
            memory_recall_limit=memory_recall_limit,
        )
        await instance._initialize()
        return instance

    @classmethod
    async def from_config(cls, agent_id: str | None = None) -> "VikingClient":
        """Create a VikingClient from the global nanobot config."""
        from nanobot.config.loader import load_config

        config = load_config()
        cfg = config.openviking
        embedding_api_key, embedding_base_url = cls._resolve_provider_credentials(
            config=config,
            model=cfg.embedding_model,
            api_key=cfg.embedding_api_key,
            api_base=cfg.embedding_base_url,
        )
        vlm_api_key, vlm_base_url = cls._resolve_provider_credentials(
            config=config,
            model=cfg.vlm_model,
            api_key=cfg.vlm_api_key,
            api_base=cfg.vlm_base_url,
        )
        return await cls.create(
            mode=cfg.mode,
            data_dir=cfg.data_dir,
            server_url=cfg.server_url,
            api_key=cfg.api_key,
            account_id=getattr(cfg, "account_id", ""),
            user_id=cfg.user_id,
            agent_id=agent_id,
            vlm_api_key=vlm_api_key,
            vlm_base_url=vlm_base_url,
            vlm_model=cfg.vlm_model,
            embedding_model=cfg.embedding_model,
            embedding_api_key=embedding_api_key,
            embedding_base_url=embedding_base_url,
            embedding_dimension=cfg.embedding_dimension,
            memory_recall_limit=cfg.memory_recall_limit,
        )

    # ------------------------------------------------------------------
    # User management (remote mode)
    # ------------------------------------------------------------------

    async def _check_user_exists(self, user_id: str) -> bool:
        """Check whether a user exists. Always True for local mode."""
        if self.mode == "local":
            return True
        try:
            res = await self.client.admin_list_users(self.account_id)
            if not res:
                return False
            return any(u.get("user_id") == user_id for u in res)
        except Exception as e:
            if self._is_optional_admin_api_error(e):
                logger.debug(
                    "OpenViking remote user existence check skipped because admin API is unavailable: {}",
                    e,
                )
                return True
            logger.warning("Failed to check user existence: {}", e)
            return False

    async def _initialize_user(self, user_id: str, role: str = "user") -> bool:
        """Register a user in the remote account. No-op for local mode."""
        if self.mode == "local":
            return True
        try:
            await self.client.admin_register_user(
                account_id=self.account_id, user_id=user_id, role=role,
            )
            return True
        except Exception as e:
            if "User already exists" in str(e) or self._is_optional_admin_api_error(e):
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

    def _effective_user_id(self, sender_id: str = "") -> str:
        if self.mode == "local":
            user = getattr(self.client, "user", None)
            if user and hasattr(user, "user_space_name"):
                return user.user_space_name()
            return "default"
        return sender_id or self.user_id

    @staticmethod
    def _derive_agent_space_name(account_id: str, user_id: str, agent_id: str) -> str:
        if UserIdentifier is not None:
            return UserIdentifier(account_id, user_id, agent_id).agent_space_name()
        return hashlib.md5(f"{user_id}:{agent_id}".encode()).hexdigest()[:12]

    @staticmethod
    def _resolve_provider_credentials(
        *,
        config: Any,
        model: str,
        api_key: str,
        api_base: str,
    ) -> tuple[str, str]:
        if not model or (api_key and api_base):
            return api_key, api_base

        provider = config.get_provider(model)
        if provider is None:
            return api_key, api_base

        return api_key or (provider.api_key or ""), api_base or (provider.api_base or "")

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
        uid = self._effective_user_id(sender_id)
        if not await self._ensure_user(uid):
            return []
        uri = f"viking://user/{uid}/memories/"
        result = await self.client.search(query, target_uri=uri)
        return [self._matched_to_dict(m) for m in getattr(result, "memories", [])]

    async def search_memory(self, query: str, limit: int = 10) -> dict[str, list[Any]]:
        """Search both user and agent memories."""
        uid = self._effective_user_id()
        if not await self._ensure_user(uid):
            return {"user_memory": [], "agent_memory": []}

        uri_user = f"viking://user/{uid}/memories/"
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
        kwargs: dict[str, Any] = {}
        if target_path:
            if target_path.endswith("/"):
                kwargs["parent"] = target_path
            else:
                kwargs["to"] = target_path
        result = await self.client.add_resource(
            path=local_path, reason=desc, wait=wait, **kwargs,
        )
        await self._attach_content_uri(result)
        return result

    async def list_resources(self, path: str | None = None, recursive: bool = False) -> list:
        if not path:
            path = "viking://resources/"
        return await self.client.ls(path, recursive=recursive)

    async def read_content(self, uri: str, level: str = "abstract") -> str:
        read_uri = uri
        try:
            if level == "abstract":
                return await self.client.abstract(uri)
            elif level == "overview":
                return await self.client.overview(uri)
            elif level == "read":
                read_uri = await self._resolve_read_uri(uri)
                return await self.client.read(read_uri)
            else:
                raise ValueError(f"Unsupported level: {level}")
        except FileNotFoundError:
            return ""
        except Exception as e:
            logger.warning("Failed to read content from {} (resolved={}): {}", uri, read_uri, e)
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
            uid = self._effective_user_id(sender_id)
            if not await self._ensure_user(uid):
                return {"success": False, "error": "Failed to initialize user"}

            actual_sid = session_id
            if hasattr(self.client, "get_session"):
                try:
                    await self.client.get_session(actual_sid, auto_create=True)
                except Exception:
                    logger.debug("get_session(auto_create=True) unavailable, falling back to create_session")
                    if hasattr(self.client, "create_session"):
                        try:
                            await self.client.create_session(actual_sid)
                        except Exception:
                            logger.debug("create_session({}) failed; continuing with session()", actual_sid)

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
                await session.add_message(role=role, parts=parts)

            result = await session.commit()
            logger.debug("Committed {} messages to OpenViking session {}", len(messages), actual_sid)
            status = result.get("status", False)
            success = (
                status is True
                or status in {"committed", "accepted", "queued"}
                or bool(result.get("task_id"))
                or result.get("archived") is True
            )
            return {"success": success}

    # ------------------------------------------------------------------
    # Memory context helpers
    # ------------------------------------------------------------------

    async def get_viking_memory_context(self, current_message: str) -> str:
        """Return formatted Viking memory context."""
        result = await self.search_memory(current_message, limit=self.memory_recall_limit)
        if not result:
            return ""
        user_text = self._format_memories(result.get("user_memory", []))
        agent_text = self._format_memories(result.get("agent_memory", []))
        if not user_text and not agent_text:
            return ""
        return (
            f"### User Memories\n{user_text or '(none)'}\n"
            f"### Agent Memories\n{agent_text or '(none)'}"
        )

    async def get_viking_user_profile(self) -> str:
        start = time.perf_counter()
        uid = self._effective_user_id()
        if not await self._ensure_user(uid):
            return ""
        content = await self.read_content(
            uri=f"viking://user/{uid}/memories/profile.md", level="read"
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
    def _is_optional_admin_api_error(exc: Exception) -> bool:
        message = str(exc)
        markers = (
            "Admin API is unavailable",
            "Development mode does not support account or user management",
            "Requires role:",
            "Permission denied",
        )
        return any(marker in message for marker in markers)

    async def _safe_stat(self, uri: str) -> dict[str, Any] | None:
        try:
            stat = await self.client.stat(uri)
            return stat if isinstance(stat, dict) else None
        except Exception:
            return None

    async def _resolve_read_uri(self, uri: str) -> str:
        stat = await self._safe_stat(uri)
        if not stat or not stat.get("isDir", False):
            return uri

        try:
            entries = await self.client.ls(uri, recursive=True)
        except Exception:
            return uri

        preferred_uri = ""
        fallback_uri = ""
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("isDir", False):
                continue
            entry_uri = entry.get("uri", "")
            if not entry_uri:
                continue
            fallback_uri = fallback_uri or entry_uri
            name = entry.get("name", "")
            if not isinstance(name, str) or name.startswith("."):
                continue
            preferred_uri = entry_uri
            break

        return preferred_uri or fallback_uri or uri

    async def _attach_content_uri(self, result: dict[str, Any] | None) -> None:
        if not isinstance(result, dict):
            return

        payload = result.get("result")
        if not isinstance(payload, dict):
            payload = result

        root_uri = payload.get("root_uri") or payload.get("temp_uri")
        if not isinstance(root_uri, str) or not root_uri:
            return

        content_uri = await self._resolve_read_uri(root_uri)
        payload["content_uri"] = content_uri
        payload["is_directory_root"] = content_uri != root_uri

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
            is_leaf = getattr(m, "is_leaf", False)
            score = getattr(m, "score", 0.0)
            lines.append(
                f"{idx}. {abstract}; uri: {uri}; isLeaf: {is_leaf}; score: {score:.2f}"
            )
        return "\n".join(lines)

    async def aclose(self) -> None:
        if self.mode == "local" and ov is not None and hasattr(ov.AsyncOpenViking, "reset"):
            await ov.AsyncOpenViking.reset()
            return
        if hasattr(self.client, "close"):
            result = self.client.close()
            if hasattr(result, "__await__"):
                await result

    def close(self) -> None:
        if self.mode == "local" and ov is not None and hasattr(ov.AsyncOpenViking, "reset"):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(ov.AsyncOpenViking.reset())
            else:
                loop.create_task(ov.AsyncOpenViking.reset())
            return
        if hasattr(self.client, "close"):
            result = self.client.close()
            if hasattr(result, "__await__"):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    asyncio.run(result)
                else:
                    loop.create_task(result)
