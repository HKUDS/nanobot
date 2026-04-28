"""Long Task Tool: meta-ReAct loop for long-running tasks via subagent steps."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, IntegerSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


# ---------------------------------------------------------------------------
# Signal tools -- write progress/completion into a shared dict
# ---------------------------------------------------------------------------

@tool_parameters(
    tool_parameters_schema(
        message=StringSchema(
            "What you completed in this step and where results are saved. "
            "The next step will pick up from here.",
        ),
        required=["message"],
    )
)
class HandoffTool(Tool):
    """Signal that the step is done but the overall task continues."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "handoff"

    @property
    def description(self) -> str:
        return (
            "REQUIRED after finishing your work in this step. "
            "Pass your progress summary to the next step. "
            "Use complete() instead if the entire goal is achieved."
        )

    async def execute(self, message: str, **kwargs: Any) -> str:
        self._store["type"] = "handoff"
        self._store["payload"] = message
        return "Progress recorded. The next step will continue from here."


@tool_parameters(
    tool_parameters_schema(
        summary=StringSchema("Final result summary of the entire task"),
        required=["summary"],
    )
)
class CompleteTool(Tool):
    """Signal that the entire long task is finished."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "complete"

    @property
    def description(self) -> str:
        return (
            "The ENTIRE goal is achieved. Call this only when nothing remains."
        )

    async def execute(self, summary: str, **kwargs: Any) -> str:
        self._store["type"] = "complete"
        self._store["payload"] = summary
        return "Task marked as complete."


# ---------------------------------------------------------------------------
# System prompt for long-task subagent steps
# ---------------------------------------------------------------------------

_STEP_BUDGET = 8

# Must match max_iterations_message set in SubagentManager.run_step()
_BUDGET_EXHAUSTED_PREFIX = "Tool budget exhausted"

_LONG_TASK_SYSTEM_PROMPT = """\
You are one step in a chain working toward a goal.

1. Check the filesystem to see what's already done.
2. Do the next piece of work. Write results to files as you go — \
do NOT just collect information without producing output.
3. When done with your chunk, call handoff() with a brief summary. \
If the entire goal is finished, call complete() instead.

IMPORTANT: Write output to files early and often. If you run out of \
tool calls, only what's on the filesystem survives.
"""


def _build_user_message(goal: str, step: int, handoff: str) -> str:
    """Build the user message for a subagent step with budget warning."""
    budget_note = (
        f"\n\n---\n"
        f"Step {step + 1}. You have {_STEP_BUDGET} tool calls total. "
        f"Call handoff() or complete() before you run out."
    )
    if step == 0:
        return goal + budget_note
    return f"{goal}\n\n## Previous Progress\n{handoff}{budget_note}"


def _extract_handoff_from_messages(messages: list[dict[str, Any]]) -> str:
    """Extract useful content from messages when no signal was called.

    Skips the generic max_iterations_message appended by the runner,
    looking for actual subagent thinking/progress text instead.
    """
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if content.startswith(_BUDGET_EXHAUSTED_PREFIX):
            continue
        return content
    return ""


# ---------------------------------------------------------------------------
# Long Task Tool — the orchestrator
# ---------------------------------------------------------------------------

@tool_parameters(
    tool_parameters_schema(
        goal=StringSchema("Description of the task to complete"),
        max_steps=IntegerSchema(
            description="Maximum number of subagent steps (default 20)",
            minimum=1,
            maximum=100,
        ),
        required=["goal"],
    )
)
class LongTaskTool(Tool):
    """Execute a long-running task via a meta-ReAct loop of subagent steps."""

    def __init__(self, manager: SubagentManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "long_task"

    @property
    def description(self) -> str:
        return (
            "Execute a long-running task that cannot fit in a single context window. "
            "The work is broken into sequential steps, each starting fresh with the "
            "original goal and progress from the previous step. Use this for batch "
            "processing (auditing many files, processing many items), large-scale "
            "refactoring, or any multi-step task where you might lose track of the "
            "goal. For simple independent tasks, use spawn instead."
        )

    async def execute(self, goal: str, max_steps: int = 20, **kwargs: Any) -> str:
        handoff = ""
        logger.debug("long_task start: max_steps={}, goal={:.120}", max_steps, goal)
        for step in range(max_steps):
            signal_store: dict[str, str] = {}
            user_msg = _build_user_message(goal, step, handoff)
            try:
                result = await self._manager.run_step(
                    system_prompt=_LONG_TASK_SYSTEM_PROMPT,
                    user_message=user_msg,
                    extra_tools=[HandoffTool(signal_store), CompleteTool(signal_store)],
                )
            except Exception:
                logger.exception("long_task step {}/{} failed", step + 1, max_steps)
                if handoff:
                    return (
                        f"Long task failed at step {step + 1}/{max_steps}. "
                        f"Last progress:\n{handoff}"
                    )
                return f"Long task failed at step {step + 1}/{max_steps}."
            sig_type = signal_store.get("type")
            sig_payload = signal_store.get("payload", "")
            logger.info(
                "long_task step {}/{}: signal={}, stop_reason={}, tools={}",
                step + 1, max_steps, sig_type or "auto",
                result.stop_reason,
                result.tools_used,
            )
            if sig_type == "complete":
                logger.debug(
                    "long_task done at step {}: complete payload={:.200}",
                    step + 1, sig_payload,
                )
                return sig_payload

            # Auto-extract progress — don't require handoff()
            if sig_type == "handoff":
                handoff = sig_payload
                logger.debug("long_task step {} handoff: {:.200}", step + 1, handoff)
            elif result.stop_reason == "completed":
                # Subagent returned text naturally (no more tool calls)
                handoff = result.final_content or ""
                logger.debug(
                    "long_task step {} natural end: {:.200}",
                    step + 1, handoff[:200] if handoff else "(empty)",
                )
            else:
                # max_iterations hit — extract whatever text the subagent produced
                handoff = _extract_handoff_from_messages(result.messages)
                logger.debug(
                    "long_task step {} auto-extract: {:.200}",
                    step + 1, handoff[:200] if handoff else "(empty)",
                )
        logger.warning("long_task exhausted max_steps={}", max_steps)
        return (
            f"Long task reached max steps ({max_steps}). "
            f"Last progress:\n{handoff}"
        )
