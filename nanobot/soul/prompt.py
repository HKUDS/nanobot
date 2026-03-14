"""System prompt builder with Soul & Memory integration.

Builds a layered system prompt that injects soul persona and memory context
into the agent's system prompt, following OpenClaw's prompt construction order.

Reference: OpenClaw src/agents/system-prompt.ts (lines 380-612)

Prompt structure:
  1. Base system prompt (identity + tools)
  2. Personality (agent-specific system_prompt)
  3. Memory Recall instructions
  4. Time / Workspace context
  5. Project Context Files (SOUL.md + MEMORY.md)
  6. Recent Memory awareness
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from nanobot.soul.workspace import AgentWorkspace, load_bootstrap_files
from nanobot.soul.tools import MemoryManager, get_memory_manager


# Memory flush prompt for context compaction
MEMORY_FLUSH_PROMPT = (
    "Pre-compaction memory flush. Store durable memories now "
    "(use memory/YYYY-MM-DD.md; create memory/ if needed). "
    "IMPORTANT: If the file already exists, APPEND new content only "
    "and do not overwrite existing entries."
)


class SoulPromptBuilder:
    """Builds system prompts with Soul & Memory sections.

    Each section is a callable that receives (workspace, base_prompt) and
    returns a string. Sections are concatenated in registration order.

    Reference: OpenClaw src/agents/system-prompt.ts buildAgentSystemPrompt()
    """

    def __init__(self) -> None:
        self._sections: list[tuple[str, Callable[[AgentWorkspace, str], str]]] = []

    def add_section(self, name: str, builder: Callable[[AgentWorkspace, str], str]) -> None:
        """Register a prompt section builder."""
        self._sections.append((name, builder))

    def build(self, workspace: AgentWorkspace, base_prompt: str) -> str:
        """Build full system prompt by concatenating all sections."""
        parts = []
        for name, builder in self._sections:
            try:
                section = builder(workspace, base_prompt)
                if section:
                    parts.append(section)
            except Exception as e:
                logger.warning("Prompt section '{}' failed: {}", name, e)
        return "\n".join(parts)


def create_default_prompt_builder(
    personality: str = "",
) -> SoulPromptBuilder:
    """Create a SoulPromptBuilder with all standard sections.

    Sections:
      base            -> base prompt passed through
      personality     -> agent personality string
      memory_recall   -> Memory Recall instructions
      time_workspace  -> current date + workspace path
      context_files   -> SOUL.md + MEMORY.md content
      recent_memory   -> recent daily memory awareness
    """
    pb = SoulPromptBuilder()

    # 1. Base prompt
    pb.add_section("base", lambda ws, base: base)

    # 2. Personality
    if personality:
        pb.add_section("personality", lambda ws, _: f"\nPersonality: {personality}")

    # 3. Memory Recall instructions
    pb.add_section("memory_recall", lambda ws, _: (
        "\n## Memory Recall\n"
        "Before answering anything about prior work, decisions, dates, people, "
        "preferences, or todos: run memory_search on MEMORY.md + memory/*.md; "
        "then use memory_get to pull only the needed lines. "
        "If low confidence after search, say you checked.\n"
        "Citations: include Source: <path#Lstart-Lend> when it helps the user "
        "verify memory snippets."
    ))

    # 4. Time / Workspace
    def _time_section(ws: AgentWorkspace, _base: str) -> str:
        return (
            f"\n## Time\nCurrent date: {date.today().isoformat()}\n"
            f"\n## Workspace\nWorking directory: {ws.workspace_dir}\n"
            "Treat this directory as the single global workspace for memory files."
        )
    pb.add_section("time_workspace", _time_section)

    # 5. Project Context Files (SOUL.md + MEMORY.md)
    def _context_files(ws: AgentWorkspace, _base: str) -> str:
        bootstrap_files = load_bootstrap_files(ws.workspace_dir)
        if not bootstrap_files:
            return ""
        parts = [
            "\n## Project Context Files\n"
            "The following project context files have been loaded from the workspace.\n"
            "If SOUL.md is present, embody its persona -- speak, think, and "
            "respond in the style it defines.\n"
        ]
        for bf in bootstrap_files:
            parts.append(f"\n### {bf['name']}\n\n{bf['content']}")
        return "\n".join(parts)
    pb.add_section("context_files", _context_files)

    # 6. Recent Memory awareness
    def _recent_memory(ws: AgentWorkspace, _base: str) -> str:
        mgr = get_memory_manager(ws.agent_id, ws.workspace_dir)
        recent = mgr.get_recent_daily(days=2)
        if not recent:
            return ""
        lines = ["\n## Recent Memory (Awareness Only)"]
        for entry in recent:
            snippet = entry["content"][:500]
            lines.append(f"\n### {entry['date']}\n{snippet}")
        return "\n".join(lines)
    pb.add_section("recent_memory", _recent_memory)

    return pb


def build_soul_system_prompt(
    workspace: AgentWorkspace,
    base_prompt: str,
    personality: str = "",
) -> str:
    """Convenience function: build a full soul+memory system prompt."""
    pb = create_default_prompt_builder(personality=personality)
    return pb.build(workspace, base_prompt)
