"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from contextlib import suppress
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any, Mapping, Sequence

from loguru import logger

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.session.goal_state import goal_state_runtime_lines
from nanobot.utils.helpers import (
    current_time_str,
    detect_image_mime,
    truncate_text,
)
from nanobot.utils.prompt_templates import render_template

from nanobot.agent.skill_index import SkillIndex
from nanobot.config.schema import SkillRetrievalConfig
from nanobot.agent.skill_selector import SkillCandidate, SkillLLMSelector
from nanobot.providers.base import LLMProvider
class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
    _MAX_RECENT_HISTORY = 50
    _MAX_HISTORY_CHARS = 32_000  # hard cap on recent history section size
    _RUNTIME_CONTEXT_END = "[/Runtime Context]"

    def __init__(
        self, 
        workspace: Path, 
        timezone: str | None = None, 
        disabled_skills: list[str] | None = None,
        skill_retrieval: SkillRetrievalConfig | None = None,
        skill_llm_provider: LLMProvider | None = None,
    ):
        self.workspace = workspace
        self.timezone = timezone
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace, disabled_skills=set(disabled_skills) if disabled_skills else None)
        self._skill_retrieval = skill_retrieval or SkillRetrievalConfig()
        self._skill_index: SkillIndex | None = None
        self._skill_llm_selector: SkillLLMSelector | None = None
        if skill_llm_provider is not None and self._uses_llm_selection():
            self._skill_llm_selector = SkillLLMSelector(skill_llm_provider, self._skill_retrieval)

    def set_skill_llm_provider(self, provider: LLMProvider | None) -> None:
        """Attach or replace the LLM used for skill selection."""
        if provider is not None and self._uses_llm_selection():
            self._skill_llm_selector = SkillLLMSelector(provider, self._skill_retrieval)
        else:
            self._skill_llm_selector = None

    def _uses_llm_selection(self) -> bool:
        return self._skill_retrieval.mode in {"llm", "hybrid", "auto"}

    def warm_skill_index(self) -> None:
        """启用检索时预热/构建磁盘 skill 索引。"""
        if not self._skill_retrieval.enable:
            return
        self._get_skill_index().warm(self.skills)

    def _get_skill_index(self) -> SkillIndex:
        """懒加载 SkillIndex 实例。"""
        if self._skill_index is None:
            self._skill_index = SkillIndex(self.workspace, self._skill_retrieval)
        return self._skill_index
        
    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        channel: str | None = None,
        session_summary: str | None = None,
        retrieval_query: str | None = None,
        skill_entries: list[dict[str, object]] | None = None,
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        logger.info("Building system prompt with retrieval query: {}", retrieval_query)
        logger.info("Skill retrieval config: {}", self._skill_retrieval)
        logger.info("Skill index: {}", self._get_skill_index())
        parts = [self._get_identity(channel=channel)]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        parts.append(render_template("agent/tool_contract.md"))

        memory = self.memory.get_memory_context()
        if memory and not self._is_template_content(self.memory.read_memory(), "memory/MEMORY.md"):
            parts.append(f"# Memory\n\n{memory}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")
        exclude = set(always_skills)
        skills_summary = self._build_skills_summary_section(
            exclude,
            retrieval_query,
            skill_entries=skill_entries,
        )
        # skills_summary = self.skills.build_skills_summary(exclude=set(always_skills))
        if skills_summary:
            parts.append(render_template("agent/skills_section.md", skills_summary=skills_summary))

        entries = self.memory.read_unprocessed_history(since_cursor=self.memory.get_last_dream_cursor())
        if entries:
            capped = entries[-self._MAX_RECENT_HISTORY:]
            history_text = "\n".join(
                f"- [{e['timestamp']}] {e['content']}" for e in capped
            )
            history_text = truncate_text(history_text, self._MAX_HISTORY_CHARS)
            parts.append("# Recent History\n\n" + history_text)

        if session_summary:
            parts.append(f"[Archived Context Summary]\n\n{session_summary}")

        return "\n\n---\n\n".join(parts)


    def _build_skills_summary_section(
        self,
        exclude: set[str],
        retrieval_query: str | None,
        skill_entries: list[dict[str, object]] | None = None,
    ) -> str:
        cfg = self._skill_retrieval
        query = (retrieval_query or "").strip()
        if skill_entries is not None:
            if skill_entries:
                return self.skills.build_skills_summary(exclude=exclude, entries=skill_entries)
            if cfg.fallback_to_full_list:
                return self._build_full_skills_summary(exclude)
            return ""
        if cfg.enable and query:
            entries = self._retrieve_skill_entries(query, exclude=exclude)
            if entries:
                return self.skills.build_skills_summary(exclude=exclude, entries=entries)
            if cfg.fallback_to_full_list:
                return self._build_full_skills_summary(exclude)
            return ""
        return self._build_full_skills_summary(exclude)


    async def resolve_skill_entries(
        self,
        query: str | None,
        *,
        exclude: set[str],
    ) -> list[dict[str, object]] | None:
        """Resolve skill summary rows for the current turn.

        Returns ``None`` when retrieval is disabled or the query is empty.
        Returns ``[]`` when selection ran but found no relevant skills.
        """
        cfg = self._skill_retrieval
        normalized = (query or "").strip()
        if not cfg.enable or not normalized:
            return None

        mode = self._effective_retrieval_mode(exclude)
        logger.info(
            "Skill resolve [start]: query={!r} mode={} config_mode={} exclude={}",
            normalized,
            mode,
            cfg.mode,
            sorted(exclude),
        )

        if mode == "fts":
            entries = self._retrieve_skill_entries(normalized, exclude=exclude)
            logger.info(
                "Skill resolve [fts done]: query={!r} selected={}",
                normalized,
                [str(entry["name"]) for entry in entries],
            )
            return entries

        if self._skill_llm_selector is None:
            logger.warning("Skill retrieval mode {} requires an LLM provider; falling back to FTS", mode)
            entries = self._retrieve_skill_entries(normalized, exclude=exclude)
            logger.info(
                "Skill resolve [fts fallback done]: query={!r} selected={}",
                normalized,
                [str(entry["name"]) for entry in entries],
            )
            return entries

        if mode == "llm":
            candidates = self._list_candidate_entries(exclude)
            logger.info(
                "Skill resolve [llm catalog]: count={} names={}",
                len(candidates),
                [str(entry["name"]) for entry in candidates],
            )
        else:
            logger.info(
                "Skill resolve [hybrid bm25 pool start]: query={!r} fts_candidate_k={}",
                normalized,
                cfg.fts_candidate_k,
            )
            candidates = self._retrieve_skill_entries(
                normalized,
                exclude=exclude,
                k=cfg.fts_candidate_k,
            )
            if not candidates:
                logger.info(
                    "Skill resolve [hybrid bm25 empty]: falling back to catalog slice",
                )
                candidates = self._list_candidate_entries(exclude)[: cfg.fts_candidate_k]
            logger.info(
                "Skill resolve [hybrid bm25 pool done]: count={} names={}",
                len(candidates),
                [str(entry["name"]) for entry in candidates],
            )

        if not candidates:
            logger.info("Skill resolve [done]: query={!r} mode={} no candidates", normalized, mode)
            return []

        skill_candidates = [
            SkillCandidate(
                name=str(entry["name"]),
                description=str(entry.get("description") or entry["name"]),
            )
            for entry in candidates
        ]
        logger.info(
            "Skill resolve [llm select start]: query={!r} top_k={} candidates={}",
            normalized,
            cfg.top_k,
            [(candidate.name, candidate.description) for candidate in skill_candidates],
        )
        selected = await self._skill_llm_selector.select(
            normalized,
            skill_candidates,
            k=cfg.top_k,
        )
        logger.info(
            "Skill resolve [llm select done]: query={!r} selected={}",
            normalized,
            selected,
        )
        if selected:
            by_name = {str(entry["name"]): entry for entry in candidates}
            result = [by_name[name] for name in selected if name in by_name]
            logger.info(
                "Skill resolve [done]: query={!r} mode={} final={}",
                normalized,
                mode,
                [str(entry["name"]) for entry in result],
            )
            return result

        if mode == "hybrid":
            logger.info(
                "Skill resolve [hybrid fallback fts start]: llm returned empty for query={!r}",
                normalized,
            )
            entries = self._retrieve_skill_entries(normalized, exclude=exclude)
            logger.info(
                "Skill resolve [hybrid fallback fts done]: query={!r} selected={}",
                normalized,
                [str(entry["name"]) for entry in entries],
            )
            return entries

        logger.info("Skill resolve [done]: query={!r} mode={} final=[]", normalized, mode)
        return []

    def _effective_retrieval_mode(self, exclude: set[str]) -> str:
        cfg = self._skill_retrieval
        if cfg.mode != "auto":
            return cfg.mode
        catalog_size = len(self._list_candidate_entries(exclude))
        mode = "llm" if catalog_size <= cfg.llm_skill_threshold else "hybrid"
        logger.info(
            "Skill resolve [auto mode]: catalog_size={} threshold={} -> {}",
            catalog_size,
            cfg.llm_skill_threshold,
            mode,
        )
        return mode

    def _list_candidate_entries(self, exclude: set[str]) -> list[dict[str, object]]:
        if self._skill_retrieval.enable:
            catalog = self._get_skill_index().list_catalog(self.skills)
            if catalog:
                entries = [entry.to_summary_dict(self.skills) for entry in catalog]
                return [entry for entry in entries if entry["name"] not in exclude]
        entries: list[dict[str, object]] = []
        for entry in self.skills.list_skills(filter_unavailable=False):
            name = str(entry["name"])
            if name in exclude:
                continue
            meta = self.skills._get_skill_meta(name)
            available = self.skills._check_requirements(meta)
            missing = self.skills._get_missing_requirements(meta) if not available else ""
            entries.append(
                {
                    "name": name,
                    "path": entry["path"],
                    "source": entry["source"],
                    "description": self.skills._get_skill_description(name),
                    "available": available,
                    "missing_requirements": missing,
                }
            )
        return entries

    def _build_full_skills_summary(self, exclude: set[str]) -> str:
        cfg = self._skill_retrieval
        if cfg.enable:
            catalog = self._get_skill_index().list_catalog(self.skills)
            if catalog:
                entries = [entry.to_summary_dict(self.skills) for entry in catalog]
                return self.skills.build_skills_summary(exclude=exclude, entries=entries)
        return self.skills.build_skills_summary(exclude=exclude)

    def _retrieve_skill_entries(
        self,
        query: str,
        *,
        exclude: set[str],
        k: int | None = None,
    ) -> list[dict[str, object]]:
        cfg = self._skill_retrieval
        effective_k = k or cfg.top_k
        logger.info(
            "Skill retrieval FTS [start]: query={!r} k={} exclude={} min_score={}",
            query,
            effective_k,
            sorted(exclude),
            cfg.min_score,
        )
        index = self._get_skill_index()
        if cfg.rebuild_on_miss:
            index.ensure_ready(self.skills)
        hits = index.retrieve(
            query,
            loader=self.skills,
            k=effective_k,
            exclude=exclude,
            min_score=cfg.min_score,
        )
        entries = [hit.to_summary_dict(self.skills) for hit in hits]
        logger.info(
            "Skill retrieval FTS [done]: query={!r} selected={}",
            query,
            [str(entry["name"]) for entry in entries],
        )
        return entries

    @staticmethod
    def _extract_retrieval_query(current_message: str | list[dict[str, Any]]) -> str | None:
        if isinstance(current_message, str):
            text = current_message.strip()
            return text or None
        if isinstance(current_message, list):
            parts = [
                str(block.get("text", ""))
                for block in current_message
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            text = "\n".join(part for part in parts if part).strip()
            return text or None
        return None

    def _get_identity(self, channel: str | None = None) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return render_template(
            "agent/identity.md",
            workspace_path=workspace_path,
            runtime=runtime,
            platform_policy=render_template("agent/platform_policy.md", system=system),
            channel=channel or "",
        )

    @staticmethod
    def _build_runtime_context(
        channel: str | None,
        chat_id: str | None,
        timezone: str | None = None,
        sender_id: str | None = None,
        supplemental_lines: Sequence[str] | None = None,
    ) -> str:
        """Build untrusted runtime metadata block appended after user content."""
        lines = [f"Current Time: {current_time_str(timezone)}"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        if sender_id:
            lines += [f"Sender ID: {sender_id}"]
        if supplemental_lines:
            lines.extend(supplemental_lines)
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines) + "\n" + ContextBuilder._RUNTIME_CONTEXT_END

    @staticmethod
    def _merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
        if isinstance(left, str) and isinstance(right, str):
            return f"{left}\n\n{right}" if left else right

        def _to_blocks(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return [item if isinstance(item, dict) else {"type": "text", "text": str(item)} for item in value]
            if value is None:
                return []
            return [{"type": "text", "text": str(value)}]

        return _to_blocks(left) + _to_blocks(right)

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _is_template_content(content: str, template_path: str) -> bool:
        """Check if *content* is identical to the bundled template (user hasn't customized it)."""
        with suppress(Exception):
            tpl = pkg_files("nanobot") / "templates" / template_path
            if tpl.is_file():
                return content.strip() == tpl.read_text(encoding="utf-8").strip()
        return False

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        current_role: str = "user",
        sender_id: str | None = None,
        session_summary: str | None = None,
        session_metadata: Mapping[str, Any] | None = None,
        current_runtime_lines: Sequence[str] | None = None,
        skill_entries: list[dict[str, object]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        extra = [
            *goal_state_runtime_lines(session_metadata),
        ]
        if current_runtime_lines:
            extra.extend(line for line in current_runtime_lines if line)
        runtime_ctx = self._build_runtime_context(
            channel,
            chat_id,
            self.timezone,
            sender_id=sender_id,
            supplemental_lines=extra or None,
        )
        user_content = self._build_user_content(current_message, media)

        # Merge runtime context and user content into a single user message
        # to avoid consecutive same-role messages that some providers reject.
        # Runtime context is appended to keep the user-content prefix stable
        # for prompt-cache hits (the context changes every turn due to time).
        if isinstance(user_content, str):
            merged = f"{user_content}\n\n{runtime_ctx}"
        else:
            merged = user_content + [{"type": "text", "text": runtime_ctx}]
        messages = [
            {
                "role": "system",
                "content": self.build_system_prompt(
                    skill_names,
                    channel=channel,
                    session_summary=session_summary,
                    retrieval_query=self._extract_retrieval_query(current_message),
                    skill_entries=skill_entries,
                ),
            },
            *history,
        ]
        if messages[-1].get("role") == current_role:
            last = dict(messages[-1])
            last["content"] = self._merge_message_content(last.get("content"), merged)
            messages[-1] = last
            return messages
        messages.append({"role": current_role, "content": merged})
        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            images.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
                "_meta": {"path": str(p)},
            })

        if not images:
            return text
        return images + [{"type": "text", "text": text}]
