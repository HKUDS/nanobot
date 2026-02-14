"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.
    
    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
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
        
        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # Mistakes log
        mistakes = self._load_mistakes()
        if mistakes:
            parts.append(f"# Mistakes Log\n\n{mistakes}")

        # Notes - topic-specific notes
        notes = self._load_notes()
        if notes:
            parts.append(f"# Notes\n\n{notes}")
        
        # Skills - progressive loading
        # 1. Always-loaded skills: include full content
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")
        
        # 2. Available skills: only show summary (agent uses read_file to load)
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")
        
        return "\n\n---\n\n".join(parts)
    
    def _get_identity(self) -> str:
        """Get the core identity section."""
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

IMPORTANT: When the user asks you to do something (read files, execute commands, search, etc.), you MUST use the appropriate tool. Do not just describe what you would do — actually use the tools to complete the task.

When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel.
For normal conversation, just respond with text - do not call the message tool.

When sending images or files via the 'message' tool, use the 'file_path' parameter to specify the path to the file.
Supported image formats: .png, .jpg, .jpeg, .gif

## Current Time
{now} ({tz})

## Runtime
{runtime}

## Workspace Structure
Your workspace (current directory) is at: {workspace_path}

### Folder Structure & Usage Guidelines

**1. MEMORY.md - Core Identity & Long-term Memory (LOADED IN CONTEXT)**
- Your core identity, user preferences, and important persistent information
- This file is loaded directly into your system prompt
- **Location**: `{workspace_path}/MEMORY.md`

**2. MISTAKES.md - Error Log (LOADED IN CONTEXT)**
- Record of all mistakes made and lessons learned
- Update immediately when errors are discovered (by you or pointed out by user)
- Include: what went wrong, why it happened, how to avoid it in the future
- **Location**: `{workspace_path}/MISTAKES.md`

**3. memory/ - Daily Logs (NOT LOADED, READ WHEN NEEDED)**
This folder contains daily conversation logs:
- `YYYY-MM-DD.md` - Daily conversation summaries (updated in real-time)
  - Update today's notes whenever there's valuable information to record
  - Summarize key points, decisions, and context from conversations
- **Location**: `{workspace_path}/memory/`
- **Note**: Daily notes are NOT automatically loaded into context. Use read_file when you need to review them.

**4. notes/ - Knowledge Base**
- Store research findings, analysis results, and reference information
- Content discovered through searches or deep analysis during task execution
- Purpose: Improve efficiency in future conversations by avoiding repeated research
- Update when you learn something useful that might be needed later

**5. skills/ - Skill Library**
- Each skill has its own subdirectory with `SKILL.md`
- Read the skill file when you need to use a specific capability
- Skills extend your abilities (search, APIs, specialized tools)

**6. AGENTS.md - Operating Rules**
- System workflows and operational guidelines
- How to handle different types of tasks

**7. SOUL.md - Your Core Identity (CRITICAL)**
- Your personality, chat style, and character traits
- The essence of who you are
- MUST strictly follow this file - it defines your soul

**8. USER.md - User Profile**
- Detailed information about the user
- Continuously update through daily interactions
- Track preferences, habits, and important user details

**9. TOOLS.md - Tool Reference**
- Available tools and how to use them
- Command syntax and examples

**10. HEARTBEAT.md - System Tasks**
- Periodic system-level tasks (different from cron jobs)
- Read and execute tasks during heartbeat cycles
- CRITICAL: If unclear whether to add to HEARTBEAT or cron, ASK the user first
  - HEARTBEAT: System maintenance, self-checks, background monitoring
  - Cron: User-scheduled reminders, notifications, time-based actions

**11. IDENTITY.md - Additional Configuration**
- Supplementary identity settings

## File Update Guidelines
- **MEMORY.md**: Write important long-term information (core identity)
- **MISTAKES.md**: Add immediately when errors are confirmed (what, why, how to avoid)
- **memory/YYYY-MM-DD.md**: Update after conversations with key takeaways (daily logs)
- **notes/*.md**: Add research findings and reusable knowledge
- **USER.md**: Continuously refine user profile through interactions
- **HEARTBEAT.md**: Only for system-level periodic tasks (ask user if unsure)

Always be helpful, accurate, and concise. When using tools, think step by step: what you know, what you need, and why you chose this tool.
"""
    
    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []
        
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        
        return "\n\n".join(parts) if parts else ""

    def _load_mistakes(self) -> str:
        """Load mistakes log from MISTAKES.md."""
        mistakes_file = self.workspace / "MISTAKES.md"
        if mistakes_file.exists():
            return mistakes_file.read_text(encoding="utf-8")
        return ""

    def _load_notes(self) -> str:
        """Load all notes from workspace/notes directory."""
        notes_dir = self.workspace / "notes"
        if not notes_dir.exists():
            return ""
        
        parts = []
        for note_file in sorted(notes_dir.glob("*.md")):
            if note_file.is_file():
                content = note_file.read_text(encoding="utf-8")
                parts.append(f"## {note_file.name}\n\n{content}")
        
        return "\n\n".join(parts) if parts else ""
    
    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
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

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names)
        if channel and chat_id:
            system_prompt += f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
        messages.append({"role": "system", "content": system_prompt})

        # History
        messages.extend(history)

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        return messages

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
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.

        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.

        Returns:
            Updated message list.
        """
        # Truncate very long results to avoid API limits (1MB for Xunfei)
        max_content_len = 100000  # ~100KB limit for safety
        if len(result) > max_content_len:
            result = result[:max_content_len] + f"\n... (truncated, {len(result) - max_content_len} more chars)"

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
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
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        
        if tool_calls:
            msg["tool_calls"] = tool_calls
        
        # Thinking models reject history without this
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        
        messages.append(msg)
        return messages
