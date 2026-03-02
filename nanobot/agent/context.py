"""Context builder for assembling agent prompts."""

from __future__ import annotations

import base64
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader

if TYPE_CHECKING:
    from nanobot.agent.budget import TokenBudget
    from nanobot.agent.memory_store import FactStore
    from nanobot.config.schema import MemoryConfig


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    # Priority order: high first; truncation cuts from end (TOOLS/IDENTITY first).
    BOOTSTRAP_FILES = ["SOUL.md", "AGENTS.md", "USER.md", "IDENTITY.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        memory_config: MemoryConfig | None = None,
        fact_store: FactStore | None = None,
        current_message: str = "",
        query_embedding: list[float] | None = None,
        token_budget: TokenBudget | None = None,
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        if memory_config is None:
            logger.debug("Context: build_system_prompt unbudgeted (no memory_config)")
            return self._build_system_prompt_unbudgeted(skill_names)

        from nanobot.agent.budget import TokenBudget

        logger.debug("Context: build_system_prompt budgeted model={} fact_store={}", model, fact_store is not None)
        budget = token_budget or TokenBudget(
            model=model,
            max_tokens=max_tokens,
            token_budget_config=memory_config.token_budget,
        )
        parts = [budget.truncate(self._get_identity(), "identity")]

        bootstrap = self._load_bootstrap_files()
        skills_section = self._load_skills_section(skill_names)
        bootstrap_and_skills = "\n\n".join(
            filter(None, [bootstrap, skills_section])
        )
        if bootstrap_and_skills:
            parts.append(budget.truncate(bootstrap_and_skills, "bootstrap"))

        memory_budget = budget.get_budget("memory")
        if fact_store is not None:
            logger.debug("Context: memory from FactStore (query_embedding={})", query_embedding is not None)
            memory = fact_store.get_memory_context(
                current_message or "general",
                token_budget=memory_budget or 800,
                query_embedding=query_embedding,
            )
            if memory:
                parts.append(budget.truncate(memory, "memory"))
            history_ctx = fact_store.get_relevant_history(
                current_message or "",
                top_k=3,
                token_budget=min(200, (memory_budget or 800) // 4),
            )
            if history_ctx:
                parts.append(history_ctx)
        else:
            logger.debug("Context: memory from flat MemoryStore (MEMORY.md)")
            memory = self.memory.get_memory_context()
            if memory:
                parts.append(
                    "# Memory\n\n"
                    + budget.truncate(memory, "memory")
                )

        return "\n\n---\n\n".join(parts)

    def _load_skills_section(self, skill_names: list[str] | None) -> str:
        """Build the skills section (always skills + summary)."""
        parts = []
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")
        return "\n\n".join(parts) if parts else ""

    def _build_system_prompt_unbudgeted(self, skill_names: list[str] | None = None) -> str:
        """Original unbudgeted system prompt (when memory_config is not set)."""
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        skills_section = self._load_skills_section(skill_names)
        if skills_section:
            parts.append(skills_section)

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Memory: managed by FactStore (SQLite) with auto-retrieval — see the memory skill for details.
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM].
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

## nanobot Guidelines
- State intent before tool calls, but NEVER predict or claim results before receiving them.
- Before modifying a file, read it first. Do not assume files or directories exist.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.
- Ask for clarification when the request is ambiguous.

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel."""

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """Build untrusted runtime metadata block for injection before the user message."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        memory_config: MemoryConfig | None = None,
        fact_store: FactStore | None = None,
        query_embedding: list[float] | None = None,
        token_budget: TokenBudget | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        system_content = self.build_system_prompt(
            skill_names,
            model=model,
            max_tokens=max_tokens,
            memory_config=memory_config,
            fact_store=fact_store,
            current_message=current_message,
            query_embedding=query_embedding,
            token_budget=token_budget,
        )
        return [
            {"role": "system", "content": system_content},
            *history,
            {"role": "user", "content": self._build_runtime_context(channel, chat_id)},
            {"role": "user", "content": self._build_user_content(current_message, media)},
        ]

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: str,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        if thinking_blocks:
            msg["thinking_blocks"] = thinking_blocks
        messages.append(msg)
        return messages
