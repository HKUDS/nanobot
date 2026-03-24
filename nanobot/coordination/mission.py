"""Background mission manager — asynchronous delegated task execution.

A *mission* is an asynchronous task that runs in the background using the
delegation engine's structured contracts, task taxonomy, and grounding
verification.  Results are delivered directly to the user via
``OutboundMessage`` (not re-injected through the agent loop).

Works with or without a coordinator: when ``routing.enabled=True`` the
coordinator classifies the task into a specialist role; otherwise a
``general`` role is used with the same contract quality.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.config.schema import AgentRoleConfig
from nanobot.coordination.task_types import TASK_TYPES, classify_task_type
from nanobot.errors import ToolExecutionError
from nanobot.observability.langfuse import (
    score_current_trace,
    update_current_span,
)
from nanobot.observability.langfuse import (
    span as langfuse_span,
)
from nanobot.observability.tracing import TraceContext
from nanobot.tools.builtin.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.tools.builtin.shell import ExecTool
from nanobot.tools.builtin.web import WebFetchTool, WebSearchTool
from nanobot.tools.registry import ToolRegistry
from nanobot.tools.tool_loop import run_tool_loop

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ExecToolConfig
    from nanobot.coordination.coordinator import Coordinator
    from nanobot.coordination.scratchpad import Scratchpad
    from nanobot.providers.base import LLMProvider
    from nanobot.tools.base import Tool


class MissionStatus(Enum):
    """Lifecycle states for a background mission."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Mission:
    """A background task executed through the delegation engine."""

    id: str
    task: str
    label: str
    role: str
    status: MissionStatus
    created_at: datetime
    completed_at: datetime | None = None
    result: str | None = None
    tools_used: list[str] = field(default_factory=list)
    grounded: bool = False
    origin_channel: str = "cli"
    origin_chat_id: str = "direct"


class MissionManager:
    """Manages background mission execution using the delegation engine.

    Missions are asynchronous delegated tasks that:
    - Route through the coordinator for role classification (when available)
    - Use structured delegation contracts with task taxonomy
    - Track grounding (tool usage) for result verification
    - Deliver results directly via ``OutboundMessage``
    - Write results to the session scratchpad for main-agent access
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        max_iterations: int = 15,
        max_concurrent: int = 3,
        result_max_chars: int = 4000,
        brave_api_key: str | None = None,
        exec_config: ExecToolConfig | None = None,
        restrict_to_workspace: bool = False,
    ) -> None:
        from nanobot.config.schema import ExecToolConfig as _Etc

        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations
        self.max_concurrent = max_concurrent
        self.result_max_chars = result_max_chars
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or _Etc()
        self.restrict_to_workspace = restrict_to_workspace

        # Set lazily by AgentLoop when coordinator is available
        self.coordinator: Coordinator | None = None
        # Set per-session by AgentLoop
        self.scratchpad: Scratchpad | None = None
        # MCP tools injected lazily by AgentLoop after _connect_mcp()
        self.mcp_tools: list[Tool] = []

        self._missions: dict[str, Mission] = {}
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(
        self,
        task: str,
        *,
        label: str | None = None,
        context: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
    ) -> Mission:
        """Launch a background mission. Returns immediately.

        Raises ``ToolExecutionError`` when at ``max_concurrent`` capacity.
        """
        if len(self._running_tasks) >= self.max_concurrent:
            raise ToolExecutionError(
                "mission_start",
                f"Maximum concurrent missions ({self.max_concurrent}) reached. "
                "Wait for a running mission to complete or cancel one first.",
            )
        mission_id = uuid.uuid4().hex[:8]
        display_label = label or (task[:30] + ("..." if len(task) > 30 else ""))

        mission = Mission(
            id=mission_id,
            task=task,
            label=display_label,
            role="pending",
            status=MissionStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
        )
        self._missions[mission_id] = mission

        bg_task = asyncio.create_task(self._execute_mission(mission, context))
        self._running_tasks[mission_id] = bg_task
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(mission_id, None))

        logger.info("Mission [{}] started: {}", mission_id, display_label)
        return mission

    def get(self, mission_id: str) -> Mission | None:
        """Look up a mission by ID."""
        return self._missions.get(mission_id)

    def list_active(self) -> list[Mission]:
        """Return all non-terminal missions."""
        terminal = {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}
        return [m for m in self._missions.values() if m.status not in terminal]

    def list_all(self) -> list[Mission]:
        """Return all missions (any status), most recent first."""
        return sorted(self._missions.values(), key=lambda m: m.created_at, reverse=True)

    def get_running_count(self) -> int:
        """Return the number of currently running missions."""
        return len(self._running_tasks)

    def cancel(self, mission_id: str) -> bool:
        """Cancel a running mission. Returns True if cancel was sent."""
        mission = self._missions.get(mission_id)
        if not mission:
            return False
        terminal = {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}
        if mission.status in terminal:
            return False
        if task := self._running_tasks.get(mission_id):
            task.cancel()
            return True
        return False

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_mission(self, mission: Mission, context: str | None) -> None:
        """Run the mission through the delegation engine."""
        mission.status = MissionStatus.RUNNING

        TraceContext.set(request_id=mission.id, agent_id=mission.role)

        async with langfuse_span(
            name="mission",
            input=mission.task[:200],
            metadata={
                "mission_id": mission.id,
                "label": mission.label,
                "role": mission.role,
            },
        ):
            try:
                role = await self._resolve_role(mission.task)
                mission.role = role.name

                task_type = classify_task_type(role.name, mission.task)
                logger.debug("Mission [{}] task_type={} role={}", mission.id, task_type, role.name)

                tools = self._build_tool_registry(role)
                system_prompt = self._build_system_prompt(role, task_type)
                user_content = self._build_user_content(mission.task, context, task_type)

                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ]

                iter_cap = 8 if task_type in ("report_writing", "general") else 12
                max_iter = min(self.max_iterations, iter_cap)
                model = role.model or self.model
                temperature = role.temperature if role.temperature is not None else self.temperature

                result, tools_used, messages = await run_tool_loop(
                    provider=self.provider,
                    tools=tools,
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=self.max_tokens,
                    max_iterations=max_iter,
                )

                # Retry if no tools used on investigation-type task
                if not tools_used and task_type not in ("report_writing",) and max_iter > 2:
                    logger.warning(
                        "Mission [{}] agent used no tools — retrying with reminder",
                        mission.id,
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "You have not used any tools yet. You MUST use the available "
                                "tools to gather real data before producing your answer. "
                                "Start by using list_dir or read_file to inspect the workspace."
                            ),
                        }
                    )
                    retry_result, retry_tools, _ = await run_tool_loop(
                        provider=self.provider,
                        tools=tools,
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=self.max_tokens,
                        max_iterations=min(max_iter, 6),
                    )
                    if retry_tools:
                        result = retry_result
                        tools_used = tools_used + retry_tools

                summary = result or "No result produced."
                if summary.lower().startswith("final\n"):
                    summary = summary[6:].lstrip()
                elif summary.lower().startswith("final:"):
                    summary = summary[6:].lstrip()

                mission.result = summary
                mission.tools_used = tools_used
                mission.grounded = len(tools_used) > 0
                mission.status = MissionStatus.COMPLETED
                mission.completed_at = datetime.now(timezone.utc)

                # Write to scratchpad if available
                if self.scratchpad:
                    await self.scratchpad.write(
                        role=role.name,
                        label=f"[mission:{mission.id}] {mission.label}",
                        content=summary,
                        metadata={
                            "grounded": mission.grounded,
                            "tools_used": tools_used,
                            "mission_id": mission.id,
                        },
                    )

                logger.info("Mission [{}] completed (grounded={})", mission.id, mission.grounded)

            except asyncio.CancelledError:
                mission.status = MissionStatus.CANCELLED
                mission.result = "Mission cancelled by user."
                mission.completed_at = datetime.now(timezone.utc)
                logger.info("Mission [{}] cancelled", mission.id)
            except Exception as exc:  # crash-barrier: mission execution
                mission.status = MissionStatus.FAILED
                mission.result = f"Mission failed: {exc}"
                mission.completed_at = datetime.now(timezone.utc)
                logger.error("Mission [{}] failed: {}", mission.id, exc)

            score_current_trace(
                name="mission_grounded",
                value=1.0 if mission.grounded else 0.0,
                comment=f"tools_used={mission.tools_used}",
            )
            update_current_span(
                output=(mission.result or "")[:200],
                metadata={
                    "status": mission.status.value,
                    "tools_used": mission.tools_used,
                },
            )

        await self._deliver_result(mission)

    # ------------------------------------------------------------------
    # Role resolution
    # ------------------------------------------------------------------

    async def _resolve_role(self, task: str) -> AgentRoleConfig:
        """Resolve the specialist role for this mission."""
        if self.coordinator:
            return await self.coordinator.route(task)
        return AgentRoleConfig(
            name="general",
            description="General-purpose assistant",
        )

    # ------------------------------------------------------------------
    # Tool registry
    # ------------------------------------------------------------------

    def _build_tool_registry(self, role: AgentRoleConfig) -> ToolRegistry:
        """Build an isolated tool set for the mission, filtered by role."""
        tools = ToolRegistry()
        allowed_dir = self.workspace if self.restrict_to_workspace else None

        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            )
        )
        tools.register(WebSearchTool(api_key=self.brave_api_key))
        tools.register(WebFetchTool())

        # MCP tools (shared instances, injected by AgentLoop)
        for tool in self.mcp_tools:
            tools.register(tool)

        # Apply role-specific tool filters
        if role.denied_tools:
            for denied in role.denied_tools:
                tools.unregister(denied)
        if role.allowed_tools is not None:
            allowed = set(role.allowed_tools)
            for tname in list(tools._tools):
                if tname not in allowed:
                    tools.unregister(tname)

        return tools

    # ------------------------------------------------------------------
    # Prompt construction (reuses delegation contract patterns)
    # ------------------------------------------------------------------

    def _build_system_prompt(self, role: AgentRoleConfig, task_type: str) -> str:
        """Build a structured system prompt using the delegation contract pattern."""
        tt = TASK_TYPES.get(task_type, TASK_TYPES["general"])

        evidence_type = tt.get("evidence", "tool output excerpts")
        output_schema = (
            "\n\nYour response MUST use this structure:\n"
            "## Findings\n<your key findings>\n\n"
            "## Evidence\n<supporting evidence: " + evidence_type + ">\n\n"
            "## Open Questions\n<anything unresolved or needing further investigation>\n\n"
            "## Confidence\n<high/medium/low with brief justification>"
        )

        parts: list[str] = [
            f"You are the **{role.name}** specialist agent running as a background mission.",
            role.system_prompt or "",
            (
                "You MUST use your available tools to complete this task. "
                "Do NOT fabricate information — always verify with tools first."
            ),
            f"Workspace: {self.workspace}",
            output_schema,
        ]
        return "\n\n".join(p for p in parts if p)

    def _build_user_content(self, task: str, context: str | None, task_type: str) -> str:
        """Build the user message with task taxonomy guidance."""
        tt = TASK_TYPES.get(task_type, TASK_TYPES["general"])
        sections: list[str] = [f"## Your Mission\n{task}"]

        if context:
            sections.append(f"### Additional Context\n{context}")

        prefer = tt.get("prefer", [])
        avoid = tt.get("avoid_first", [])
        if prefer or avoid:
            lines: list[str] = []
            if prefer:
                lines.append(f"Preferred tools: {', '.join(prefer)}")
            if avoid:
                lines.append(
                    f"Avoid using first (use only if preferred tools insufficient): "
                    f"{', '.join(avoid)}"
                )
            sections.append("## Tool Guidance\n" + "\n".join(lines))

        completion = tt.get("completion", "")
        if completion:
            sections.append(f"## Completion Criteria\n{completion}")

        anti_h = tt.get("anti_hallucination", "")
        if anti_h:
            sections.append(f"## Evidence Rules\n{anti_h}")

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Result delivery
    # ------------------------------------------------------------------

    async def _deliver_result(self, mission: Mission) -> None:
        """Send the mission result directly to the user via the bus."""
        if mission.status == MissionStatus.COMPLETED:
            grounded_tag = "✓ verified" if mission.grounded else "⚠ unverified"
            body = (
                f"**Background mission complete** — {mission.label}\n"
                f"({grounded_tag}, {len(mission.tools_used)} tools used)\n\n"
                f"{mission.result or 'No result.'}"
            )
        elif mission.status == MissionStatus.CANCELLED:
            body = f"**Background mission cancelled** — {mission.label}"
        else:
            body = (
                f"**Background mission failed** — {mission.label}\n\n"
                f"{mission.result or 'Unknown error.'}"
            )

        # Truncate to avoid flooding the channel
        if len(body) > self.result_max_chars:
            body = body[: self.result_max_chars - 50] + "\n\n… (truncated)"

        msg = OutboundMessage(
            channel=mission.origin_channel,
            chat_id=mission.origin_chat_id,
            content=body,
            metadata={"mission_id": mission.id},
        )
        try:
            await self.bus.publish_outbound(msg)
        except Exception as exc:  # crash-barrier: bus delivery
            logger.error("Mission [{}] result delivery failed: {}", mission.id, exc)
