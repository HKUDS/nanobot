"""Long Task Tool: meta-ReAct loop for long-running tasks via subagent steps."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.context import ToolContext


# ---------------------------------------------------------------------------
# Structured handoff state
# ---------------------------------------------------------------------------

@dataclass
class HandoffState:
    """Structured progress state passed between long-task steps."""

    signal_type: str = ""
    message: str = ""
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    next_step_hint: str = ""
    verification: str = ""

    def is_empty(self) -> bool:
        return not any(
            [
                self.signal_type,
                self.message,
                self.files_created,
                self.files_modified,
                self.next_step_hint,
                self.verification,
            ]
        )


# ---------------------------------------------------------------------------
# Signal tools -- write progress/completion into a shared state
# ---------------------------------------------------------------------------

@tool_parameters(
    tool_parameters_schema(
        message=StringSchema(
            "What you completed in this step and where results are saved. "
            "The next step will pick up from here.",
        ),
        files_created=ArraySchema(
            StringSchema(""),
            description="List of file paths you created in this step",
        ),
        files_modified=ArraySchema(
            StringSchema(""),
            description="List of file paths you modified in this step",
        ),
        next_step_hint=StringSchema(
            "A clear, specific hint about what the next step should do. "
            "Be concrete — e.g. 'Implement the test cases in test_foo.py'",
        ),
        verification=StringSchema(
            "Any verification you performed (tests run, lint passed, etc.)",
        ),
        required=["message"],
    )
)
class HandoffTool(Tool):
    """Signal that the step is done but the overall task continues."""

    _plugin_discoverable = False

    def __init__(self, store: HandoffState) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "handoff"

    @property
    def description(self) -> str:
        return (
            "You are done with this step. Pass control to the next step. "
            "You MUST call this (or complete()) before your tool budget runs out. "
            "Provide a detailed summary, list files changed, and hint the next step."
        )

    async def execute(
        self,
        message: str,
        files_created: list[str] | None = None,
        files_modified: list[str] | None = None,
        next_step_hint: str = "",
        verification: str = "",
        **kwargs: Any,
    ) -> str:
        self._store.signal_type = "handoff"
        self._store.message = message
        self._store.files_created = list(files_created or [])
        self._store.files_modified = list(files_modified or [])
        self._store.next_step_hint = next_step_hint
        self._store.verification = verification
        return "Progress recorded. The next step will continue from here."


@tool_parameters(
    tool_parameters_schema(
        summary=StringSchema("Final result summary of the entire task"),
        required=["summary"],
    )
)
class CompleteTool(Tool):
    """Signal that the entire long task is finished."""

    _plugin_discoverable = False

    def __init__(self, store: HandoffState) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "complete"

    @property
    def description(self) -> str:
        return (
            "The ENTIRE goal is achieved. Call this only when nothing remains. "
            "Your claim will be validated — if unproven, the task continues.\n\n"
            "IMPORTANT: The summary you provide here will be returned to the parent "
            "agent as the FINAL ANSWER to the user. Include all key findings, data, "
            "and conclusions directly in the summary. Do NOT rely on the parent agent "
            "reading files afterwards — it sees ONLY this summary."
        )

    async def execute(self, summary: str, **kwargs: Any) -> str:
        self._store.signal_type = "complete"
        self._store.message = summary
        return "Task marked as complete. Awaiting validation."


# ---------------------------------------------------------------------------
# Budget and prompt helpers
# ---------------------------------------------------------------------------

_STEP_BUDGET = 8
_FINAL_STEP_BUDGET = 4  # Lower budget for final steps

# Must match max_iterations_message set in SubagentManager.run_step()
_BUDGET_EXHAUSTED_PREFIX = "Tool budget exhausted"


def _step_budget(step: int, max_steps: int) -> int:
    """Compute per-step tool budget based on progress."""
    if step >= max_steps - 2:
        return _FINAL_STEP_BUDGET
    return _STEP_BUDGET


def _build_system_prompt(budget: int) -> str:
    """Build the system prompt for a subagent step."""
    return (
        "You are one step in a chain working toward a goal.\n\n"
        "Rules:\n"
        "1. Do ONE small chunk of work per step.\n"
        "2. Write results to files — do NOT just collect information.\n"
        "3. Call handoff() when done with your chunk. "
        "Call complete() ONLY if the ENTIRE goal is achieved.\n"
        f"4. You have {budget} tool calls. "
        "Reserve the last 1-2 for handoff() or complete()."
    )


def _build_user_message(
    goal: str,
    step: int,
    max_steps: int,
    handoff: HandoffState,
    correction: str | None = None,
) -> str:
    """Build the user message for a subagent step using templates."""
    budget = _step_budget(step, max_steps)
    budget_note = (
        f"\n\n---\n"
        f"Step {step + 1} of {max_steps}. You have {budget} tool calls for this step. "
        f"Reserve the last 1-2 calls for handoff() or complete(). "
        f"If you run out of calls without calling one, your progress is LOST."
    )

    if step == 0:
        prompt = render_template(
            "agent/long_task/step_start.md",
            step=step,
            max_steps=max_steps,
            goal=goal,
            budget=budget,
        )
    elif step >= max_steps - 2:
        prompt = render_template(
            "agent/long_task/step_final.md",
            step=step,
            max_steps=max_steps,
            goal=goal,
            budget=budget,
            handoff=handoff,
        )
    else:
        prompt = render_template(
            "agent/long_task/step_middle.md",
            step=step,
            max_steps=max_steps,
            goal=goal,
            budget=budget,
            handoff=handoff,
        )

    if correction:
        prompt += f"\n\n## User Correction\n{correction}\n"

    return prompt + budget_note


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


def _extract_write_path(detail: str) -> str | None:
    prefix = "Successfully wrote "
    marker = " to "
    if not detail.startswith(prefix) or marker not in detail:
        return None
    return detail.rsplit(marker, 1)[1].strip()


def _extract_edit_path(detail: str) -> str | None:
    for prefix in ("Successfully created ", "Successfully edited "):
        if detail.startswith(prefix):
            return detail.removeprefix(prefix).strip()
    return None


def _extract_file_changes(
    tool_events: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Extract file creation/modification events from tool events."""
    created: list[str] = []
    modified: list[str] = []
    for event in tool_events:
        name = event.get("name", "")
        status = event.get("status", "")
        detail = event.get("detail", "")
        if status != "ok":
            continue
        if name == "write_file":
            path = _extract_write_path(detail)
            if path:
                created.append(path)
            else:
                logger.debug(
                    "long_task: skipping file event with unexpected detail: {}",
                    detail[:80],
                )
        elif name == "edit_file":
            path = _extract_edit_path(detail)
            if path:
                modified.append(path)
            else:
                logger.debug(
                    "long_task: skipping file event with unexpected detail: {}",
                    detail[:80],
                )
    return created, modified


# ---------------------------------------------------------------------------
# Observability: events and hooks
# ---------------------------------------------------------------------------

@dataclass
class LongTaskEvent:
    """Event emitted during long-task execution for observability."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


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

    # NOT available in subagent scope to prevent recursive long_task nesting.
    _scopes: set[str] = {"core"}

    def __init__(self, manager: SubagentManager) -> None:
        self._manager = manager
        self._hooks: dict[str, Any] = {}
        self._state: dict[str, Any] = {"signal_queue": []}
        self._reset_state()

    def _reset_state(self) -> None:
        """Reset internal state before a new execution.

        Preserves any pending user corrections so inject_correction() can be
        called before execute() starts.
        """
        existing_signals = self._state.get("signal_queue", [])
        self._state: dict[str, Any] = {
            "current_step": 0,
            "total_steps": 0,
            "goal": "",
            "status": "idle",  # idle, running, validating, completed, error
            "last_handoff": HandoffState(),
            "cumulative_usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "signal_queue": existing_signals,
            "error": None,
        }

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
            "goal. For simple independent tasks, use spawn instead.\n\n"
            "When constructing the goal, be explicit: list concrete deliverables, "
            "required output format (e.g. Markdown table), and any file paths. "
            "The tool returns a text summary when finished. "
            "If the summary contains the full answer, present it to the user directly. "
            "Only read files afterwards if the user explicitly asks for verification."
        )

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.subagent_manager is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(manager=ctx.subagent_manager)

    # --- State exposure for WebUI observability ---

    @property
    def current_step(self) -> int:
        return self._state["current_step"]

    @property
    def total_steps(self) -> int:
        return self._state["total_steps"]

    @property
    def status(self) -> str:
        return self._state["status"]

    @property
    def last_handoff(self) -> HandoffState:
        return self._state["last_handoff"]

    @property
    def cumulative_usage(self) -> dict[str, int]:
        return dict(self._state["cumulative_usage"])

    @property
    def goal(self) -> str:
        return self._state["goal"]

    # --- External signal mechanism (for user correction) ---

    def inject_correction(self, message: str) -> None:
        """Inject a user correction message to be read before the next step."""
        self._state["signal_queue"].append(message)
        logger.info("LongTask correction injected: {}", message[:120])

    def _pop_signal(self) -> str | None:
        """Consume and return the oldest pending correction, if any."""
        if self._state["signal_queue"]:
            return self._state["signal_queue"].pop(0)
        return None

    # --- Hook system for WebUI and logging ---

    def set_hooks(self, hooks: dict[str, Any]) -> None:
        """Register observability hooks.

        Supported hooks (all optional):
        - on_task_start(goal, max_steps)
        - on_step_start(step, goal, budget)
        - on_step_complete(step, result, handoff)
        - on_handoff(step, handoff)
        - on_validation_started(step, completion_summary)
        - on_validation_passed(step, summary)
        - on_validation_failed(step, reason)
        - on_task_complete(step, summary)
        - on_task_error(step, error)
        - on_event(event: LongTaskEvent)  # catch-all
        """
        self._hooks = dict(hooks)

    def _emit(self, event_type: str, **payload: Any) -> None:
        """Emit an event to registered hooks."""
        event = LongTaskEvent(type=event_type, payload=payload)

        # Call catch-all hook
        catch_all = self._hooks.get("on_event")
        if catch_all is not None:
            try:
                catch_all(event)
            except Exception:
                logger.exception("LongTask on_event hook failed")

        # Call specific hook
        hook_name = f"on_{event_type}"
        hook = self._hooks.get(hook_name)
        if hook is not None:
            try:
                hook(**payload)
            except Exception:
                logger.exception("LongTask {} hook failed", hook_name)

    # --- Core execution ---

    async def execute(self, goal: str, max_steps: int = 20, **kwargs: Any) -> str:
        handoff = HandoffState()
        self._reset_state()
        self._state["goal"] = goal
        self._state["total_steps"] = max_steps
        self._state["status"] = "running"

        logger.debug("long_task start: max_steps={}, goal={:.120}", max_steps, goal)
        self._emit("task_start", goal=goal, max_steps=max_steps)

        for step in range(max_steps):
            self._state["current_step"] = step
            signal_store = HandoffState()
            correction = self._pop_signal()
            user_msg = _build_user_message(
                goal, step, max_steps, handoff, correction=correction
            )

            budget = _step_budget(step, max_steps)
            self._emit("step_start", step=step, goal=goal, budget=budget)

            # Run the step with retry on crash
            result = await self._run_step_with_retry(
                system_prompt=_build_system_prompt(budget),
                user_message=user_msg,
                extra_tools=[HandoffTool(signal_store), CompleteTool(signal_store)],
                step=step,
                budget=budget,
            )

            if result is None:
                # Fatal error after retry
                self._state["status"] = "error"
                logger.error(
                    "long_task step {}/{} failed after retry: {}",
                    step + 1, max_steps, self._state["error"],
                )
                self._emit("task_error", step=step, error=self._state["error"])
                if handoff.message:
                    return (
                        f"Long task failed at step {step + 1}/{max_steps}. "
                        f"Last progress:\n{handoff.message}"
                    )
                return f"Long task failed at step {step + 1}/{max_steps}."

            # Accumulate usage
            usage = getattr(result, "usage", {}) or {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                self._state["cumulative_usage"][key] += usage.get(key, 0)

            # Extract file changes from tool events for automatic tracking
            tool_events = getattr(result, "tool_events", []) or []
            auto_created, auto_modified = _extract_file_changes(tool_events)
            if auto_created or auto_modified:
                logger.debug(
                    "long_task step {}: auto-detected files created={}, modified={}",
                    step + 1,
                    auto_created,
                    auto_modified,
                )

            self._emit("step_complete", step=step, result=result, handoff=signal_store)

            # Determine signal from tool events
            sig_type = "none"
            for event in reversed(tool_events):
                ev_name = event.get("name", "")
                if ev_name == "complete":
                    sig_type = "complete"
                    break
                elif ev_name == "handoff":
                    sig_type = "handoff"
                    break

            # Fallback: if no explicit signal but CompleteTool/HandoffTool was
            # called but the runner did not expose tool events, trust the store.
            if sig_type == "none" and signal_store.signal_type:
                sig_type = signal_store.signal_type
            elif sig_type == "none":
                signal_store.message = _extract_handoff_from_messages(
                    getattr(result, "messages", []) or []
                )
                if signal_store.message:
                    sig_type = "handoff"

            sig_payload = signal_store.message
            logger.info(
                "long_task step {}/{}: signal={}, stop_reason={}, tools={}",
                step + 1,
                max_steps,
                sig_type,
                result.stop_reason,
                result.tools_used,
            )

            if sig_type == "complete":
                # Validation round
                self._state["status"] = "validating"
                self._emit(
                    "validation_started",
                    step=step,
                    completion_summary=sig_payload,
                )

                validated = await self._validate_completion(
                    goal, sig_payload, max_steps
                )
                if validated:
                    self._state["status"] = "completed"
                    logger.info(
                        "long_task complete at step {}/{} after validation",
                        step + 1, max_steps,
                    )
                    self._emit("task_complete", step=step, summary=sig_payload)
                    return (
                        "The task is complete. This is the final answer — "
                        "present it to the user directly without calling additional "
                        "tools or reading files.\n\n"
                        f"{sig_payload}"
                    )
                else:
                    logger.warning(
                        "long_task validation failed at step {}/{}",
                        step + 1, max_steps,
                    )
                    self._emit(
                        "validation_failed",
                        step=step,
                        reason="Validation did not confirm completion",
                    )
                    # Fall through to handoff — continue working
                    handoff = signal_store
                    handoff.next_step_hint = (
                        f"Validation failed. Continue working toward the goal. "
                        f"Previous claim: {sig_payload}"
                    )
                    self._state["last_handoff"] = handoff
                    continue

            elif sig_type == "handoff":
                self._emit("handoff_received", step=step, handoff=signal_store)
                # Merge auto-detected file changes if not explicitly reported
                if auto_created and not signal_store.files_created:
                    signal_store.files_created = auto_created
                if auto_modified and not signal_store.files_modified:
                    signal_store.files_modified = auto_modified
                handoff = signal_store
                self._state["last_handoff"] = handoff
                continue

            else:
                # No signal — use extracted content as handoff
                handoff = HandoffState(message=signal_store.message)
                self._state["last_handoff"] = handoff

        self._state["status"] = "error"
        logger.error("long_task reached max steps ({})", max_steps)
        self._emit("task_error", step=max_steps, error="Max steps reached")
        return (
            f"Long task reached max steps ({max_steps}). "
            f"Last progress:\n{handoff.message}"
        )

    async def _run_step_with_retry(
        self,
        system_prompt: str,
        user_message: str,
        extra_tools: list[Any],
        step: int,
        budget: int,
    ) -> Any:
        """Run a single step with one retry on crash."""
        try:
            return await self._manager.run_step(
                system_prompt=system_prompt,
                user_message=user_message,
                extra_tools=extra_tools,
                max_iterations=budget,
            )
        except Exception as first_err:
            logger.warning(
                "long_task step {}/{} crashed (will retry once): {}",
                step + 1,
                self._state["total_steps"],
                first_err,
            )
            try:
                return await self._manager.run_step(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    extra_tools=extra_tools,
                    max_iterations=budget,
                )
            except Exception as second_err:
                logger.exception(
                    "long_task step {}/{} failed after retry",
                    step + 1,
                    self._state["total_steps"],
                )
                self._state["error"] = str(second_err)
                return None

    async def _validate_completion(
        self, goal: str, completion_summary: str, max_steps: int
    ) -> bool:
        """Run a validation step to verify the completion claim."""
        try:
            validation_store = HandoffState()
            validation_prompt = render_template(
                "agent/long_task/validation.md",
                goal=goal,
                completion_summary=completion_summary,
            )
            result = await self._manager.run_step(
                system_prompt=validation_prompt,
                user_message="Validate the claimed completion. "
                "Call complete() if verified, handoff() if not.",
                extra_tools=[
                    HandoffTool(validation_store),
                    CompleteTool(validation_store),
                ],
                max_iterations=4,  # Short validation step
            )
            # If complete() was called, validation passed
            tool_events = getattr(result, "tool_events", []) or []
            for event in tool_events:
                if event.get("name") == "complete":
                    self._emit("validation_passed", summary=completion_summary)
                    return True

            self._emit(
                "validation_failed",
                reason=validation_store.message or "Validator did not confirm",
            )
            return False
        except Exception:
            logger.exception("Validation step failed")
            return False
