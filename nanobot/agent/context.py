"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.media_cache import MediaCache
from nanobot.agent.memory import MemoryStore
from nanobot.agent.skill_ranker import SkillRanker
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
        self.skill_ranker = SkillRanker(self.skills)
        self.media_cache = MediaCache(workspace)

    def build_system_prompt(self, skill_names: list[str] | None = None, user_query: str | None = None) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # Skills - smart injection via TF-IDF relevance ranking
        always_skills = self.skills.get_always_skills()

        if user_query:
            # Smart injection: always + top-K relevant skills get full content
            inject_full, _ = self.skill_ranker.get_relevant_skills(
                query=user_query,
                always_skills=always_skills,
                top_k=3,
                threshold=0.05,
            )
        else:
            # Fallback: only always-skills get full content
            inject_full = always_skills

        if inject_full:
            full_content = self.skills.load_skills_for_context(inject_full)
            if full_content:
                parts.append(f"# Active Skills\n\n{full_content}")

        # Remaining skills: summary only (agent reads full content on demand)
        skills_summary = self.skills.build_skills_summary(exclude=set(inject_full) if inject_full else None)
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

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
- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable)
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
        system_prompt_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.
            channel: Current channel (telegram, feishu, etc.).
            chat_id: Current chat/user ID.
            system_prompt_prefix: Optional text prepended to the system prompt
                (e.g. from a named agent profile set via ``cron add --agent``).

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names, user_query=current_message)
        if system_prompt_prefix:
            system_prompt = system_prompt_prefix + "\n\n" + system_prompt
        messages.append({"role": "system", "content": system_prompt})

        # History
        messages.extend(history)

        # Runtime context as a separate untrusted user message (metadata only, not instructions)
        messages.append({"role": "user", "content": self._build_runtime_context(channel, chat_id)})

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(
        self,
        text: str,
        media: list[str] | None,
        skip_cached: bool = False,
    ) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images.

        Args:
            text: The user's text message.
            media: Optional list of local file paths.
            skip_cached: If True, already-cached images are injected as text
                         descriptions instead of being re-encoded (used when
                         the vision model has already transcribed them).
        """
        if not media:
            return text

        parts: list[dict[str, Any]] = []
        cached_descriptions: list[str] = []

        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                # Non-image or missing file — try cache anyway
                file_hash = self.media_cache.hash_file(path) if Path(path).exists() else None
                desc = self.media_cache.get(file_hash) if file_hash else None
                if desc:
                    cached_descriptions.append(f"[Image: {p.name}]\n{desc}")
                continue

            file_hash = self.media_cache.hash_file(p)
            cached = self.media_cache.get(file_hash) if file_hash else None

            if cached:
                # Already transcribed — inject description as text, skip base64
                cached_descriptions.append(f"[Image: {p.name}]\n{cached}")
            elif not skip_cached:
                # Fresh image — encode as base64 for vision model
                b64 = base64.b64encode(p.read_bytes()).decode()
                parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        # Build final content
        text_parts = []
        if cached_descriptions:
            text_parts.append("Previously transcribed images:\n" + "\n\n".join(cached_descriptions))
        text_parts.append(text)
        full_text = "\n\n".join(text_parts)

        if not parts:
            return full_text
        return parts + [{"type": "text", "text": full_text}]

    def build_vision_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        media: list[str],
        context_window: int = 6,
    ) -> list[dict[str, Any]]:
        """Build a focused message list for the vision model (preprocessor role).

        The vision model receives:
        - A tightly scoped system prompt describing its transcription role
        - The last ``context_window`` turns of conversation history so it
          understands WHAT is being asked about the image
        - The current user message + image(s) as base64

        Returns:
            Messages list for provider.chat() — no tools, no agent loop.
        """
        system = (
            "You are a vision analysis assistant. "
            "The user is chatting with an AI agent and has attached one or more images. "
            "Your job is to describe each image in rich, structured detail so the main "
            "agent can answer the user's question WITHOUT seeing the raw image again.\n\n"
            "Guidelines:\n"
            "- Describe visual content thoroughly: layout, text, charts, numbers, labels\n"
            "- For screenshots: capture UI state, visible text, error messages verbatim\n"
            "- For charts/graphs: describe axes, values, trends, colour coding\n"
            "- For photos: describe objects, scene, any text visible\n"
            "- Tailor depth to what the conversation context suggests is important\n"
            "- End with a one-line summary: 'Summary: <what the image shows>'\n\n"
            "Conversation context follows (to understand what matters in this image)."
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

        # Inject trimmed history so vision model understands the conversation
        if history and context_window > 0:
            trimmed = history[-context_window:]
            # Strip tool_calls / tool results — vision model doesn't need those
            for m in trimmed:
                role = m.get("role", "")
                if role in ("user", "assistant") and not m.get("tool_calls"):
                    content = m.get("content", "")
                    if isinstance(content, str) and content.strip():
                        messages.append({"role": role, "content": content})

        # Current message + raw images (no cache bypass here — these are fresh)
        user_content = self._build_user_content(current_message, media, skip_cached=False)
        messages.append({"role": "user", "content": user_content})

        return messages
    
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
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        messages.append(msg)
        return messages
