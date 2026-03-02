"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
    
    def __init__(self, workspace: Path, memory_daily_subdir: str = ""):
        self.workspace = workspace
        self.memory_daily_subdir = memory_daily_subdir
        self.memory = MemoryStore(workspace, daily_subdir=memory_daily_subdir)
        self.skills = SkillsLoader(workspace)
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

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

        return "\n\n---\n\n".join(parts)
    
    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        data_dir = str(Path.home() / ".nanobot")
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        daily_path = f"{workspace_path}/memory/{self.memory_daily_subdir}" if self.memory_daily_subdir else f"{workspace_path}/memory"

        return f"""# Kaguya 🐈
Powered by nanobot.

You can read and edit file, exec command, search web, send message and spawn subagents.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {daily_path}/YYYY-MM-DD.md
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM].
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md
- Logs(用于排查自身问题、token 用量等)
    - 通用日志: {data_dir}/logs/nanobot_YYYY-MM-DD.log
    - 重启日志: {data_dir}/restart.log

## Message Rules
- Default: for normal conversation, reply directly with assistant text; do not call the message tool.
- Use message tool only when needed (e.g., directly send sticker, long task progress notice, explicit out-of-band delivery, or cross-chat/channel send).
- If you judge no reply is needed, output exactly [SILENT]
- IMPORTANT: message tool 和最终文本回复去重：
  - 如果 message tool 发的是阶段性通知，最终可以继续给一条总结文本。
  - 如果 message tool 已经发了完整最终答案，最终文本必须是 [SILENT]，避免重复。
- Sticker rules:
  - 入站贴纸会出现在用户消息里，如 [sticker: 😀 (set_name)] 或 [sticker: 😀]；把它当作用户语义的一部分来理解。
  - 发送 Telegram 贴纸时，使用 message tool 的 `sticker_id` 参数（Telegram file_id）。"""
    
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
        current_timestamp: datetime | str | None = None,
        current_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        return [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
            {"role": "user", "content": self._build_runtime_context(channel, chat_id)},
            {
                "role": "user",
                "content": self._build_user_content(
                    current_message,
                    media,
                    current_timestamp,
                    metadata=current_metadata,
                ),
            },
        ]

    @staticmethod
    def _format_message_time(timestamp: datetime | str | None) -> str:
        """Normalize timestamp to local-time text for prompt."""
        if not timestamp:
            return ""
        if isinstance(timestamp, datetime):
            # Convert UTC-aware or naive datetime to local time
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone().replace(tzinfo=None)
            return timestamp.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(timestamp, str):
            try:
                dt = datetime.fromisoformat(timestamp)
                if dt.tzinfo is not None:
                    dt = dt.astimezone().replace(tzinfo=None)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                return timestamp
        return str(timestamp)

    @classmethod
    def _append_message_time(cls, text: str, timestamp: datetime | str | None) -> str:
        """Append time suffix for the current user message."""
        if "current_time" in text:
            return text
        formatted = cls._format_message_time(timestamp)
        if not formatted:
            return text
        return f"{text}\n\n[current_time {formatted}]"

    def _build_user_content(
        self,
        text: str,
        media: list[str] | None,
        timestamp: datetime | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        collected = metadata.get("collected_messages") if metadata else None
        if isinstance(collected, list) and collected:
            grouped_blocks = self._build_collected_user_content(collected)
            if grouped_blocks:
                return grouped_blocks

        images = self._build_image_blocks(media)
        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def _build_collected_user_content(self, collected: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build interleaved blocks for buffered messages to preserve text-image association."""
        blocks: list[dict[str, Any]] = []
        use_sender_prefix = len(collected) > 1

        for item in collected:
            sender = str(item.get("sender_id", "user"))
            content = str(item.get("content", ""))
            timestamp = item.get("timestamp")
            text = f"[{sender}] {content}" if use_sender_prefix else content
            blocks.append({"type": "text", "text": text})
            blocks.extend(self._build_image_blocks(item.get("media")))

        return blocks

    @staticmethod
    def _build_image_blocks(media: list[str] | None) -> list[dict[str, Any]]:
        """Build image blocks from local media paths."""
        if not media:
            return []

        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        return images
    
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
