"""Delegation contract construction and context helpers.

Extracted from ``delegation.py`` (Task 2 of the delegation decomposition plan).
All former instance methods are now module-level functions that accept explicit
parameters instead of reading from ``self``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.prompt_loader import prompts
from nanobot.agent.task_types import TASK_TYPES

if TYPE_CHECKING:
    from nanobot.agent.scratchpad import Scratchpad

__all__ = [
    "_SCRATCHPAD_INJECTION_LIMIT",
    "_cap_scratchpad_for_injection",
    "build_delegation_contract",
    "build_execution_context",
    "build_parallel_work_summary",
    "extract_plan_text",
    "extract_user_request",
    "gather_recent_tool_results",
]

_SCRATCHPAD_INJECTION_LIMIT: int = 4_000


def _cap_scratchpad_for_injection(content: str, limit: int = _SCRATCHPAD_INJECTION_LIMIT) -> str:
    """Truncate scratchpad content for delegation injection to avoid context bloat."""
    if len(content) <= limit:
        return content
    return (
        content[:limit] + f"\n\n[truncated — {len(content) - limit:,} chars omitted. "
        "Use scratchpad_read tool for full content.]"
    )


def gather_recent_tool_results(
    active_messages: list[dict[str, Any]],
    max_results: int = 15,
    max_chars: int = 8000,
) -> str:
    """Extract recent tool results from the current turn only.

    Takes a snapshot of *active_messages* at call time to guard against
    concurrent mutation (LAN-110). Scopes results to messages after the
    last user message to prevent cross-turn bleed (LAN-111).
    """
    if not active_messages:
        return ""
    # Snapshot to prevent mutation during iteration (LAN-110).
    messages = list(active_messages)
    # Find the start of the current turn: last user message (LAN-111).
    turn_start = 0
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            turn_start = i
    current_turn = messages[turn_start:]
    tool_results: list[str] = []
    total_chars = 0
    for m in reversed(current_turn):
        if m.get("role") != "tool":
            continue
        name = m.get("name", "unknown")
        content = m.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        entry = f"**{name}**: {content}"
        if total_chars + len(entry) > max_chars:
            break
        tool_results.append(entry)
        total_chars += len(entry)
        if len(tool_results) >= max_results:
            break
    if not tool_results:
        return ""
    tool_results.reverse()
    return "\n\n".join(tool_results)


def extract_plan_text(active_messages: list[dict[str, Any]]) -> str:
    """Pull the plan from *active_messages* if planning was triggered."""
    if not active_messages:
        return ""
    found_plan_prompt = False
    for m in list(active_messages):  # snapshot for LAN-110
        if found_plan_prompt and m.get("role") == "assistant":
            content = m.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
            return ""
        if (
            m.get("role") == "system"
            and isinstance(m.get("content"), str)
            and "outline a numbered plan" in m["content"]
        ):
            found_plan_prompt = True
    return ""


def extract_user_request(active_messages: list[dict[str, Any]]) -> str:
    """Pull the original user message from *active_messages*."""
    if not active_messages:
        return ""
    for m in list(active_messages):  # snapshot for LAN-110
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                return content.strip()
    return ""


def build_execution_context(workspace: Path, task_type: str) -> str:
    """Assemble project knowledge with tier-based stratification."""
    parts: list[str] = [f"Workspace: {workspace}"]
    try:
        entries = sorted(workspace.iterdir())
        tree_lines = []
        for entry in entries[:50]:
            suffix = "/" if entry.is_dir() else ""
            tree_lines.append(f"  {entry.name}{suffix}")
        if tree_lines:
            parts.append("Directory layout:\n" + "\n".join(tree_lines))
    except OSError as exc:
        logger.debug("Directory listing failed for {}: {}", workspace, exc)
    if task_type in ("local_code_analysis", "repo_architecture", "bug_investigation", "hybrid"):
        for name in ("AGENTS.md", "README.md", "SOUL.md"):
            path = workspace / name
            try:
                if path.is_file():
                    text = path.read_text(encoding="utf-8", errors="replace")[:1500]
                    if text.strip():
                        parts.append(f"--- {name} (excerpt) ---\n{text.strip()}")
            except OSError as exc:
                logger.debug("Failed to read {}: {}", path, exc)
    return "\n\n".join(parts)


def build_parallel_work_summary(scratchpad: Scratchpad | None, role: str) -> str:
    """Build a brief summary of what other agents are doing."""
    if not scratchpad:
        return ""
    entries = scratchpad.list_entries()
    if not entries:
        return ""
    lines: list[str] = []
    for e in entries:
        if e.get("role") == role:
            continue
        lines.append(f"- [{e.get('role', '?')}] {e.get('label', '')[:60]}")
    return "\n".join(lines) if lines else ""


def build_delegation_contract(
    role: str,
    task: str,
    context: str | None,
    task_type: str,
    workspace: Path,
    active_messages: list[dict[str, Any]],
    scratchpad: Scratchpad | None,
) -> tuple[str, str]:
    """Build a typed delegation contract.

    Returns ``(user_content, output_schema_instruction)``.
    """
    tt = TASK_TYPES.get(task_type, TASK_TYPES["general"])
    sections: list[str] = []

    # --- Tier A: always present ---
    user_request = extract_user_request(active_messages)
    if user_request:
        sections.append(f"## Original User Request\n{user_request}")
    sections.append(f"## Your Mission\n{task}")
    if context:
        sections.append(f"### Additional Context\n{context}")
    sections.append(f"## Project Root\n`{workspace.name}`")

    non_goals: list[str] = []
    avoid = tt.get("avoid_first", [])
    if avoid:
        non_goals.append(f"Do not start with: {', '.join(avoid)}")
    parallel = build_parallel_work_summary(scratchpad, role)
    if parallel:
        sections.append(f"## Other Agents' Work (do not duplicate)\n{parallel}")
        non_goals.append("Do not duplicate work already done by other agents.")
    if non_goals:
        sections.append("## Non-Goals\n" + "\n".join(f"- {g}" for g in non_goals))

    prefer = tt.get("prefer", [])
    tool_lines: list[str] = []
    if prefer:
        tool_lines.append(f"Preferred tools: {', '.join(prefer)}")
    if avoid:
        tool_lines.append(
            f"Avoid using first (use only if preferred tools insufficient): {', '.join(avoid)}"
        )
    if tool_lines:
        sections.append("## Tool Guidance\n" + "\n".join(tool_lines))

    completion = tt.get("completion", "")
    if completion:
        sections.append(f"## Completion Criteria\n{completion}")
    anti_h = tt.get("anti_hallucination", "")
    if anti_h:
        sections.append(f"## Evidence Rules\n{anti_h}")

    # --- Tier B: when available ---
    plan_text = extract_plan_text(active_messages)
    if plan_text:
        sections.append(f"## Overall Plan (for context)\n{plan_text}")
    # Skip workspace I/O for synthesis-only tasks where context is unused (LAN-126).
    if task_type != "report_writing":
        execution_ctx = build_execution_context(workspace, task_type)
        if execution_ctx:
            sections.append(f"## Project Context\n{execution_ctx}")
    parent_findings = gather_recent_tool_results(active_messages)
    if parent_findings:
        sections.append(f"## Prior Results\n{parent_findings}")

    evidence_type = tt.get("evidence", "tool output excerpts")
    output_schema = "\n\n" + prompts.render("delegation_schema", evidence_type=evidence_type)

    return "\n\n".join(sections), output_schema
