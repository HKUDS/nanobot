"""Context builder for assembling agent prompts.

This module is responsible for constructing the complete message array
sent to the LLM on each iteration.  Key responsibilities:

- **System prompt assembly** — combines base personality, skill
  instructions, memory context (``MEMORY.md`` excerpt + retrieved events),
  tool schemas, and session metadata into a single system message.
- **Token budgeting** — estimates token usage and ensures the assembled
  context fits within the model's context window.

Compression logic (token truncation, tool-result dropping, LLM-based
summarisation) lives in :mod:`nanobot.context.compression`.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from nanobot.context.feedback_context import feedback_summary
from nanobot.context.prompt_loader import prompts
from nanobot.context.skills import SkillsLoader
from nanobot.errors import (
    MemoryRetrievalError,
)
from nanobot.errors import (
    MemorySubsystemError as NanobotMemoryError,
)
from nanobot.observability.tracing import bind_trace

if TYPE_CHECKING:
    from nanobot.memory.store import MemoryStore

# ---------------------------------------------------------------------------
# Module-level platform info cache — avoid repeated syscalls on every LLM
# iteration (platform.system() and platform.python_version() are cheap but
# unnecessary to call more than once per process).
# ---------------------------------------------------------------------------

_PLATFORM_INFO: str = f"{platform.system()} / Python {platform.python_version()}"


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.

    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(
        self,
        workspace: Path,
        *,
        memory: MemoryStore | None = None,
        memory_retrieval_k: int = 6,
        memory_token_budget: int = 900,
        memory_md_token_cap: int = 1500,
        role_system_prompt: str = "",
    ):
        self.workspace = workspace
        self.memory = memory
        self.skills = SkillsLoader(workspace)
        self.memory_retrieval_k = memory_retrieval_k
        self.memory_token_budget = memory_token_budget
        self.memory_md_token_cap = memory_md_token_cap
        self.role_system_prompt = role_system_prompt
        self._contacts_context: str = ""
        self._unavailable_tools_fn: Callable[[], str] | None = None
        # P-03: mtime-keyed cache for bootstrap files — avoids re-reading static
        # workspace files on every LLM iteration within the same agent turn.
        self._bootstrap_cache: str | None = None
        self._bootstrap_cache_mtimes: dict[str, float] = {}

    def set_unavailable_tools_fn(self, fn: Callable[[], str]) -> None:
        """Register a callback that returns the unavailable-tools summary."""
        self._unavailable_tools_fn = fn

    def set_contacts_context(self, contacts: list[str]) -> None:
        """Update the known contacts displayed in the system prompt."""
        if contacts:
            lines = "\n".join(f"- {addr}" for addr in contacts)
            self._contacts_context = (
                "# Known Contacts\n\n"
                "These are the ONLY email addresses you may send to. "
                "Do NOT invent or guess email addresses.\n\n" + lines
            )
        else:
            self._contacts_context = ""

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        current_message: str | None = None,
    ) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.

        Args:
            skill_names: Optional list of skills to include.

        Returns:
            Complete system prompt.
        """
        parts = []

        # Core identity
        parts.append(self._get_identity())

        # Role-specific system prompt (multi-agent routing)
        if self.role_system_prompt:
            parts.append(f"# Agent Role\n\n{self.role_system_prompt}")

        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Memory context — graceful degradation if retrieval crashes
        if self.memory is not None:
            try:
                memory = self.memory.get_memory_context(
                    query=current_message,
                    retrieval_k=self.memory_retrieval_k,
                    token_budget=self.memory_token_budget,
                    memory_md_token_cap=self.memory_md_token_cap,
                )
            except (NanobotMemoryError, MemoryRetrievalError, RuntimeError, OSError):
                logger.warning("Memory context retrieval failed; continuing without memory")
                memory = ""
            if memory:
                parts.append(prompts.render("memory_header", memory=memory))

            # Feedback summary — surface correction stats so the agent adapts
            events_file = self.memory.events_file
            fb_summary = feedback_summary(events_file)
            if fb_summary:
                parts.append(f"# Feedback\n\n{fb_summary}")

        # Skills - progressive loading
        # 1. Always-on skills only: full content injection
        always_skills = self.skills.get_always_skills()
        if always_skills:
            active_content = self.skills.load_skills_for_context(always_skills)
            if active_content:
                parts.append(f"# Active Skills\n\n{active_content}")

        # 2. Unified summary — matched skills highlighted, all others listed
        matched_skills = skill_names or []
        skills_summary = self.skills.build_skills_summary(matched=matched_skills)
        if skills_summary:
            parts.append(prompts.render("skills_header", skills_summary=skills_summary))

        # Security: prompt-injection advisory (SEC-M1, LAN-43)
        # Tool results (web pages, files, shell output) may contain adversarial
        # instructions.  The structural <tool_result> tags create an explicit boundary
        # between untrusted tool output and agent instructions.
        parts.append(prompts.get("security_advisory"))

        # Unavailable tools — tell the LLM what it cannot use this session
        if self._unavailable_tools_fn:
            unavail = self._unavailable_tools_fn()
            if unavail:
                parts.append(prompts.render("unavailable_tools", unavail=unavail))

        # Known contacts (email recipients, populated by channel manager)
        if self._contacts_context:
            parts.append(self._contacts_context)

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        _sys_name, _py_ver = _PLATFORM_INFO.split(" / ", 1)
        runtime = (
            f"{'macOS' if _sys_name == 'Darwin' else _sys_name} {platform.machine()}, {_py_ver}"
        )

        return prompts.render("identity", runtime=runtime, workspace_path=workspace_path)

    @staticmethod
    def _inject_runtime_context(
        user_content: str | list[dict[str, Any]],
        channel: str | None,
        chat_id: str | None,
    ) -> str | list[dict[str, Any]]:
        """Append dynamic runtime context to the tail of the user message."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        block = "[Runtime Context]\n" + "\n".join(lines)
        if isinstance(user_content, str):
            return f"{user_content}\n\n{block}"
        return [*user_content, {"type": "text", "text": block}]

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace (P-03: mtime-cached)."""
        # Check whether any file's mtime has changed since last load.
        current_mtimes: dict[str, float] = {}
        for filename in self.BOOTSTRAP_FILES:
            fp = self.workspace / filename
            try:
                current_mtimes[filename] = fp.stat().st_mtime if fp.exists() else -1.0
            except OSError:
                current_mtimes[filename] = -1.0

        if self._bootstrap_cache is not None and current_mtimes == self._bootstrap_cache_mtimes:
            return self._bootstrap_cache

        parts = []
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        result = "\n\n".join(parts) if parts else ""
        self._bootstrap_cache = result
        self._bootstrap_cache_mtimes = current_mtimes
        return result

    async def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        verify_before_answer: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.
            channel: Current channel (telegram, discord, etc.).
            chat_id: Current chat/user ID.

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names, current_message=current_message)
        if verify_before_answer:
            system_prompt += "\n\n" + prompts.get("verification_required")
        messages.append({"role": "system", "content": system_prompt})

        # History
        messages.extend(history)

        # Current message (with optional image attachments)
        user_content = await self._build_user_content(current_message, media)
        user_content = self._inject_runtime_context(user_content, channel, chat_id)
        messages.append({"role": "user", "content": user_content})  # type: ignore[dict-item]

        bind_trace().debug(
            "context_built | history={} | skills={} | total_msgs={}",
            len(history),
            len(skill_names or []),
            len(messages),
        )
        return messages

    async def _build_user_content(
        self, text: str, media: list[str] | None
    ) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            data = await asyncio.to_thread(p.read_bytes)
            b64 = base64.b64encode(data).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self, messages: list[dict[str, Any]], tool_call_id: str, tool_name: str, result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.

        The result content is wrapped in ``<tool_result>`` XML tags to create a
        structural boundary between untrusted tool output and agent instructions
        (prompt-injection mitigation, LAN-43).  Double-wrapping is avoided: if
        the content is already tagged it is passed through unchanged.

        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.

        Returns:
            Updated message list.
        """
        if result.startswith("<tool_result>"):
            wrapped = result
        else:
            wrapped = f"<tool_result>\n{result}\n</tool_result>"
        messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": wrapped}
        )
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.

        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.
            reasoning_content: Thinking output (Kimi, DeepSeek-R1, etc.).

        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant"}

        # Always include content — some providers (e.g. StepFun) reject
        # assistant messages that omit the key entirely.
        msg["content"] = content

        if tool_calls:
            msg["tool_calls"] = tool_calls

        # Include reasoning content when provided (required by some thinking models)
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content

        messages.append(msg)
        return messages
