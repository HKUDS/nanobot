"""Context builder for assembling agent prompts."""

import base64
import mimetypes
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.memory_store import MemoryStore
from nanobot.agent.skills import SkillsLoader

try:
    from nanobot.agent.memory.store import VectorMemoryStore, EmbeddingService
    VECTOR_MEMORY_AVAILABLE = True
except ImportError:
    VECTOR_MEMORY_AVAILABLE = False


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(self, workspace: Path, use_vector_memory: bool = True, embedding_model: str = "text-embedding-3-small", max_memories: int = 1000):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)

        self.vector_memory: VectorMemoryStore | None = None
        if use_vector_memory and VECTOR_MEMORY_AVAILABLE:
            try:
                vector_db_path = Path("memory/vectors.db")
                embedding_service = EmbeddingService(model=embedding_model)
                self.vector_memory = VectorMemoryStore(
                    db_path=vector_db_path,
                    base_dir=workspace,
                    embedding_service=embedding_service,
                    max_memories=max_memories
                )
                logger.debug(f"Vector memory initialized at {workspace / vector_db_path}")
            except Exception as e:
                logger.warning(f"Failed to initialize vector memory: {e}")

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        query: str | None = None,
        namespace: str | None = None,
    ) -> str:
        """Build the system prompt from bootstrap files, memory, and skills."""
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory_context = self._build_memory_context(query, namespace)
        if memory_context:
            parts.append(f"# Memory\n\n{memory_context}")

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

    def _build_memory_context(self, query: str | None = None, namespace: str | None = None) -> str:
        """Build memory context, using JIT retrieval when possible."""
        parts = []

        file_memory = self.memory.get_memory_context()
        if file_memory:
            parts.append("## Notes\n" + file_memory)

        if self.vector_memory and query:
            try:
                results = self.vector_memory.search(query, top_k=5, threshold=0.7, namespace=namespace)
                if results:
                    vector_memories = [
                        f"- {item.content} (relevance: {score:.0%})"
                        for item, score in results
                    ]
                    parts.append("## Recalled Facts\n" + "\n".join(vector_memories))
            except Exception as e:
                logger.warning(f"Vector memory search failed: {e}")

        return "\n\n".join(parts) if parts else ""

    def _get_identity(self) -> str:
        """Get the core identity section."""
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        workspace_path = str(self.workspace.expanduser().resolve())

        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

## Current Time
{now}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, explain what you're doing.
When remembering something, write to {workspace_path}/memory/MEMORY.md"""

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
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        messages = []

        system_prompt = self.build_system_prompt(skill_names, query=current_message, namespace=namespace)
        messages.append({"role": "system", "content": system_prompt})

        messages.extend(history)

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
        """Add a tool result to the message list."""
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
        tool_calls: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)
        return messages

    def close(self) -> None:
        """Clean up resources."""
        if self.vector_memory:
            self.vector_memory.close()

    def __del__(self):
        self.close()
