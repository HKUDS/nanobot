"""Thin integration layer for skill self-evolution features.

All skill-related wiring is centralised here so that upstream files
(loop.py, memory.py, server.py) only need a single import + call,
minimising merge conflicts when syncing from the upstream fork.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.skills import SkillsLoader
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.events import OutboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import SkillsConfig
    from nanobot.providers.base import LLMProvider


# ── loop.py helpers ──────────────────────────────────────────────


def register_skill_tools(
    tools: ToolRegistry,
    catalog: SkillsLoader,
    workspace: Path,
    skills_config: SkillsConfig,
) -> Any | None:
    """Register skill tools into *tools* and return a SkillStore (or None).

    Called once from ``AgentLoop._register_default_tools``.
    """
    from nanobot.agent.tools.skills import SkillsListTool, SkillViewTool

    skill_store = None

    if skills_config.enabled:
        from nanobot.agent.skill_evo.skill_store import SkillStore
        from nanobot.agent.tools.skills import SkillManageTool

        guard = None
        if skills_config.guard_enabled:
            from nanobot.agent.skill_evo.skill_guard import SkillGuard
            guard = SkillGuard()

        skill_store = SkillStore(
            workspace=workspace,
            builtin_skills_dir=catalog.builtin_skills,
            guard=guard,
        )
        tools.register(SkillManageTool(
            store=skill_store,
            catalog=catalog,
            config=skills_config,
        ))

    tools.register(SkillsListTool(catalog=catalog))
    tools.register(SkillViewTool(catalog=catalog, store=skill_store))
    return skill_store


def create_review_service(
    provider: LLMProvider,
    model: str,
    skill_store: Any,
    catalog: SkillsLoader,
    skills_config: SkillsConfig,
) -> Any | None:
    """Create a SkillReviewService if configured, else return None."""
    if not skills_config.review_enabled or skill_store is None:
        return None
    from nanobot.agent.skill_evo.skill_review import SkillReviewService
    return SkillReviewService(
        provider=provider,
        model=model,
        store=skill_store,
        catalog=catalog,
        config=skills_config,
    )


class SkillReviewTracker:
    """Tracks iteration counts and decides when to trigger a background review.

    Instantiated once and stored on AgentLoop; keeps all skill-review
    state out of the loop class itself.
    """

    __slots__ = ("_config", "_review", "_iters_since_skill", "_last_seen_iters")

    def __init__(self, skills_config: SkillsConfig, review_service: Any | None) -> None:
        self._config = skills_config
        self._review = review_service
        self._iters_since_skill: int = 0
        self._last_seen_iters: int = 0

    @property
    def active(self) -> bool:
        return self._review is not None

    async def maybe_review(
        self,
        all_msgs: list[dict[str, Any]],
        session_key: str,
        tools_used: set[str],
        *,
        bus: MessageBus | None = None,
        channel: str = "",
        chat_id: str = "",
    ) -> None:
        """Evaluate whether a review should be scheduled and run it.

        Designed to be called inside ``_schedule_background`` (fire-and-forget).
        """
        if self._review is None:
            return

        distinct_tools = len(tools_used)
        total_tool_calls = sum(
            len(m.get("tool_calls") or [])
            for m in all_msgs
            if m.get("role") == "assistant" and m.get("tool_calls")
        )
        total_iterations = sum(
            1 for m in all_msgs
            if m.get("role") == "assistant" and m.get("tool_calls")
        )

        # Only count NEW iterations since last call (avoid double-counting
        # from the full session history that all_msgs contains).
        new_iters = max(0, total_iterations - self._last_seen_iters)
        self._last_seen_iters = total_iterations

        if "skill_manage" in tools_used:
            self._iters_since_skill = 0
            return

        self._iters_since_skill += new_iters

        # Primary gate: accumulated iterations must reach the configured
        # threshold (default 10, matching hermes-agent's nudge interval).
        # The min_tool_calls check uses total tool calls (not distinct names)
        # as a secondary "complexity" filter.
        should_trigger = (
            self._iters_since_skill >= self._config.review_trigger_iterations
            and total_tool_calls >= self._config.review_min_tool_calls
        )

        logger.debug(
            "Skill review gate: iters_acc={} (threshold={}), "
            "new_iters={}, tool_calls={} (threshold={}), "
            "distinct_tools={}, trigger={}",
            self._iters_since_skill, self._config.review_trigger_iterations,
            new_iters, total_tool_calls, self._config.review_min_tool_calls,
            distinct_tools, should_trigger,
        )

        if not should_trigger:
            return

        self._iters_since_skill = 0
        logger.info("Skill review triggered for session {}", session_key)
        actions = await self._review.review_turn(
            list(all_msgs),
            session_key,
            tool_call_count=total_tool_calls,
            iteration_count=total_iterations,
            tools_used=sorted(tools_used),
        )

        if actions and self._config.notify_user_on_change and bus is not None:
            parts = []
            for a in actions:
                verb = "created" if a["action"] == "create" else "updated"
                parts.append(f"**{a['skill']}** ({verb})")
            note = "\U0001f4be Skill auto-saved: " + ", ".join(parts)
            try:
                from nanobot.bus.events import OutboundMessage
                await bus.publish(OutboundMessage(
                    channel=channel, chat_id=chat_id, content=note,
                ))
            except Exception:
                logger.debug("Failed to send skill review notification")


# ── memory.py (Dream) helper ────────────────────────────────────


def build_dream_skill_tools(workspace: Path) -> ToolRegistry:
    """Build the minimal ToolRegistry that Dream needs for skill creation.

    Replaces the inline tool construction previously in ``Dream._build_tools``.
    """
    from nanobot.agent.skill_evo.skill_guard import SkillGuard
    from nanobot.agent.skill_evo.skill_store import SkillStore
    from nanobot.agent.skills import BUILTIN_SKILLS_DIR, SkillsLoader
    from nanobot.agent.tools.skills import SkillManageTool, SkillsListTool, SkillViewTool
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.config.schema import SkillsConfig

    tools = ToolRegistry()

    catalog = SkillsLoader(workspace, builtin_skills_dir=BUILTIN_SKILLS_DIR)
    tools.register(SkillsListTool(catalog=catalog))

    skills_config = SkillsConfig()
    store = SkillStore(
        workspace=workspace,
        builtin_skills_dir=BUILTIN_SKILLS_DIR,
        guard=SkillGuard() if skills_config.guard_enabled else None,
        session_key="dream",
    )
    tools.register(SkillViewTool(catalog=catalog, store=store))
    tools.register(SkillManageTool(store=store, catalog=catalog, config=skills_config))
    return tools


# ── server.py (upload hardening) helper ─────────────────────────


_UPLOAD_MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10 MB


def validate_upload_zip(content: bytes) -> str | None:
    """Return an error message if the zip content fails size checks, else None."""
    if len(content) > _UPLOAD_MAX_ZIP_SIZE:
        return f"Zip file exceeds {_UPLOAD_MAX_ZIP_SIZE // (1024 * 1024)}MB limit"
    return None


def check_zip_path_traversal(member: str, resolved_target: Path) -> str | None:
    """Return an error message if *member* escapes *resolved_target*, else None."""
    dest = (resolved_target / member).resolve()
    try:
        dest.relative_to(resolved_target)
    except ValueError:
        return f"Zip contains path traversal entry: {member}"
    return None


def validate_uploaded_skill(skill_dir: Path) -> str | None:
    """Validate frontmatter and run guard on an extracted skill directory.

    Returns an error message string if blocked, else None.
    On failure the caller should clean up *skill_dir*.
    """
    skill_file = skill_dir / "SKILL.md"
    if skill_file.exists():
        from nanobot.agent.skill_evo.skill_store import _parse_frontmatter
        fm = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        if not fm.get("name") and not fm.get("description"):
            return "SKILL.md must have frontmatter with 'name' or 'description'"

    try:
        from nanobot.agent.skill_evo.skill_guard import SkillGuard
        guard = SkillGuard()
        scan_result = guard.scan_skill(skill_dir)
        allowed, reason = guard.should_allow(scan_result)
        if not allowed:
            return f"Security scan blocked: {reason}"
    except Exception:
        pass  # guard failure is non-fatal for uploads
    return None
