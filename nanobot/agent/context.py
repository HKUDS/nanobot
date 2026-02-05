"""Context builder for assembling agent prompts."""

import base64
import mimetypes
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader

# Template for TOOLS.md when created for the first time
TOOLS_MD_TEMPLATE = """# Tool Usage Patterns

This file tracks your knowledge about tools - when to use them, common mistakes, and best practices.
Update this file when you learn something new about using a tool effectively.

## MCP Tools

MCP (Model Context Protocol) tools are provided by external servers. After installing a new MCP server,
document the tools here with usage patterns.

<!-- Example:
### github_create_issue
- Use when: User explicitly requests creating a GitHub issue
- Avoid when: User just mentions a bug without asking to file it
- Best practices: Always confirm repo and issue details first

### filesystem_read_file
- Use when: Need to read file contents from allowed directories
- Avoid when: File path is outside allowed directories
- Learned: Works better with absolute paths
-->

## Native Tools

### read_file
- Use when: Need to read file contents
- Best practices: Prefer this over exec with cat

### write_file
- Use when: Creating or overwriting files
- Best practices: Include full content, not patches

### edit_file
- Use when: Making targeted changes to existing files
- Best practices: Use for surgical edits, write_file for full rewrites

### exec
- Use when: Need to run shell commands
- Avoid when: A more specific tool exists (use read_file over cat)
- Best practices: Set appropriate timeout for long-running commands

### web_search
- Use when: Need current information not in knowledge base
- Best practices: Use specific search queries

### web_fetch
- Use when: Need to retrieve content from a specific URL
- Best practices: Check if URL is accessible first

### message
- Use when: Need to send proactive messages to chat channels
- Avoid when: Just responding in conversation (reply directly instead)

### spawn
- Use when: Need to run long-running or parallel background tasks
- Best practices: Use for tasks that don't need immediate response

### cron
- Use when: Need to schedule tasks for specific times or intervals
- Best practices: Use 'at' for one-time, 'cron' for recurring

### install_mcp_server
- Use when: User wants to add new MCP server capabilities
- Best practices: Verify package name and command before installing
"""


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
        self._ensure_tools_md()

    def _ensure_tools_md(self) -> None:
        """Create TOOLS.md with template if it doesn't exist."""
        tools_md = self.workspace / "TOOLS.md"
        if not tools_md.exists():
            try:
                tools_md.write_text(TOOLS_MD_TEMPLATE, encoding="utf-8")
                logger.info("Created TOOLS.md template")
            except Exception as e:
                logger.warning(f"Failed to create TOOLS.md: {e}")

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
        """Get the core identity section, loading from IDENTITY.md if available."""
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        workspace_path = str(self.workspace.expanduser().resolve())

        # Try to load identity from IDENTITY.md
        identity_file = self.workspace / "IDENTITY.md"
        if identity_file.exists():
            try:
                identity_content = identity_file.read_text(encoding="utf-8")
                return self._build_identity_with_context(identity_content, now, workspace_path)
            except Exception as e:
                logger.warning(f"Failed to load IDENTITY.md, using defaults: {e}")

        # Fallback to hardcoded defaults if IDENTITY.md doesn't exist
        return self._get_default_identity(now, workspace_path)

    def _build_identity_with_context(self, identity_content: str, now: str, workspace_path: str) -> str:
        """Build identity from IDENTITY.md content with dynamic context appended."""
        return f"""{identity_content}

## Current Context

**Time**: {now}
**Workspace**: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

{self._get_capabilities_section(workspace_path)}

{self._get_tool_usage_section(workspace_path)}"""

    def _get_default_identity(self, now: str, workspace_path: str) -> str:
        """Get the hardcoded default identity (fallback when IDENTITY.md doesn't exist)."""
        return f"""# nanobot

You are nanobot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks
- Schedule tasks and reminders

## Current Time
{now}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

{self._get_capabilities_section(workspace_path)}

{self._get_tool_usage_section(workspace_path)}

Always be helpful, accurate, and concise. When using tools, explain what you're doing.
When remembering something, write to {workspace_path}/memory/MEMORY.md"""

    def _get_capabilities_section(self, workspace_path: str) -> str:
        """Get the proactive capabilities section."""
        return f"""## Proactive Capabilities

### Scheduled Jobs (cron tool)
You can schedule tasks using the `cron` tool:
- **One-time reminders**: `schedule_type="at"` with ISO datetime (e.g., "2025-02-06T09:00:00")
- **Recurring tasks**: `schedule_type="every"` with seconds (min 60), or `schedule_type="cron"` with expression
- **Deliver to user**: Set `deliver=true` to message the user when the job runs

Example cron expressions:
- `0 9 * * *` = 9 AM daily
- `0 9 * * 1-5` = 9 AM weekdays
- `*/30 * * * *` = every 30 minutes
- `0 */2 * * *` = every 2 hours

### Heartbeat Tasks (HEARTBEAT.md)
The file `{workspace_path}/HEARTBEAT.md` is checked every ~30 minutes.
- Add tasks as markdown checkboxes: `- [ ] Task description`
- You'll be asked to read and act on any tasks listed

**When to use cron vs heartbeat:**
- Use **cron** for precise timing (9 AM daily, every 2 hours)
- Use **HEARTBEAT.md** for approximate periodic checks (~30 min)

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool."""

    def _get_tool_usage_section(self, workspace_path: str) -> str:
        """Get the tool usage knowledge section."""
        return f"""## Tool Usage Knowledge

You maintain a knowledge file at {workspace_path}/TOOLS.md that tracks:
- When to use each tool
- Common mistakes to avoid
- Best practices learned from experience

When you learn something new about using a tool effectively, update TOOLS.md.
Read TOOLS.md at the start of complex tasks to refresh your knowledge.

## MCP (Model Context Protocol) Tools

MCP tools extend your capabilities by connecting to external servers. You can:
- Install new MCP servers using the `install_mcp_server` tool
- After installation, nanobot restarts to load the new server
- MCP tool names are prefixed with the server name (e.g., `github_create_issue`)

When you install a new MCP server, document its tools in TOOLS.md."""

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
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names)
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
        self, messages: list[dict[str, Any]], tool_call_id: str, tool_name: str, result: str
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
        messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result}
        )
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.

        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.

        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}

        if tool_calls:
            msg["tool_calls"] = tool_calls

        messages.append(msg)
        return messages
