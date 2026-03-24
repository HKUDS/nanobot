"""Delegation routing, contract construction, and execution.

``DelegationDispatcher`` encapsulates the multi-agent delegation sub-system
that was originally embedded in ``AgentLoop``.  It handles:

- **Routing** — resolving the target role via the ``Coordinator``
- **Cycle detection** — per-coroutine ContextVar ancestry tracking
- **Contract construction** — typed delegation contracts with task taxonomy
- **Execution** — isolated tool registries for delegated agents
- **Tracing** — routing trace JSONL + metrics recording

Extracted per ADR-002 to keep AgentLoop focused on orchestration.
"""

from __future__ import annotations

import contextvars
import json
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    ProgressCallback,
)
from nanobot.config.schema import AgentRoleConfig, ExecToolConfig
from nanobot.context.prompt_loader import prompts
from nanobot.coordination.delegation_contract import (
    _cap_scratchpad_for_injection,
    build_delegation_contract,
)
from nanobot.coordination.task_types import classify_task_type
from nanobot.errors import NanobotError
from nanobot.metrics import delegation_latency_seconds, delegation_total
from nanobot.observability.langfuse import span as langfuse_span
from nanobot.observability.tracing import sanitize_for_trace
from nanobot.tools.builtin.delegate import (
    DelegateParallelTool,
    DelegateTool,
    DelegationResult,
    _CycleError,
)
from nanobot.tools.builtin.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from nanobot.tools.builtin.shell import ExecTool
from nanobot.tools.builtin.web import WebFetchTool, WebSearchTool
from nanobot.tools.registry import ToolRegistry
from nanobot.tools.tool_loop import run_tool_loop

if TYPE_CHECKING:
    from nanobot.coordination.coordinator import Coordinator
    from nanobot.coordination.scratchpad import Scratchpad
    from nanobot.providers.base import LLMProvider
    from nanobot.tools.base import Tool
    from nanobot.tools.executor import ToolExecutor

# Per-coroutine delegation ancestry — isolated across asyncio.gather branches.
_delegation_ancestry: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "_delegation_ancestry", default=()
)


def get_delegation_depth() -> int:
    """Return the current delegation ancestry depth (0 = top-level agent)."""
    return len(_delegation_ancestry.get())


# Hard structural depth cap — raises _CycleError if the ancestry chain exceeds
# this limit. Cannot be ignored by the LLM. Each level can run up to
# max_iterations LLM calls, so uncapped chains multiply cost exponentially.
# Compare with DelegationDispatcher.max_delegations, which is a per-session
# budget enforced in dispatch() (LAN-132).
MAX_DELEGATION_DEPTH: int = 3


@dataclass(slots=True, frozen=True)
class DelegationConfig:
    """Immutable delegation settings (LAN-144).

    Groups parameters that are set once at startup and never mutated
    during a session.  Mutable per-session wiring (provider, coordinator,
    scratchpad, etc.) remains as separate ``DelegationDispatcher.__init__``
    parameters.
    """

    workspace: Path
    model: str
    temperature: float
    max_tokens: int
    max_iterations: int
    restrict_to_workspace: bool
    brave_api_key: str | None
    exec_config: ExecToolConfig | None
    role_name: str


class DelegationDispatcher:
    """Manages delegation routing, contract construction, execution, and tracing."""

    def __init__(
        self,
        *,
        config: DelegationConfig,
        provider: LLMProvider,
        coordinator: Coordinator | None = None,
        scratchpad: Scratchpad | None = None,
        active_messages: list[dict[str, Any]] | None = None,
        tools: ToolExecutor | None = None,
        mcp_tools: list[Tool] | None = None,
        on_progress: ProgressCallback | None = None,
        max_delegation_depth: int = 8,
    ) -> None:
        """Initialise the delegation dispatcher.

        Parameters
        ----------
        config:
            Immutable delegation settings (workspace, model, temperature,
            max_tokens, max_iterations, restrict_to_workspace, brave_api_key,
            exec_config, role_name).  See ``DelegationConfig``.
        provider:
            LLM provider used for delegated agent tool loops.
        coordinator:
            Coordinator instance used to classify and route delegation
            targets.  ``None`` disables delegation (calls to ``dispatch``
            will raise).
        scratchpad:
            Shared scratchpad for inter-agent artifact exchange.  Delegated
            agents read prior findings from and write results to this
            scratchpad.
        active_messages:
            Reference to the parent agent's message list, used to extract
            recent tool results and the original user request for context
            injection into delegation contracts.
        tools:
            Parent ``ToolExecutor`` used to locate delegate/delegate_parallel
            tool instances during ``wire_delegate_tools``.
        mcp_tools:
            Additional MCP-provided tool instances to include in delegated
            agent tool sets (subject to role allow/deny filtering).
        on_progress:
            Optional async callback invoked with delegation start/end events
            for progress reporting.
        """
        self.config = config
        self.provider = provider
        # Unpack config fields for concise access throughout the class body.
        # This avoids changing 750+ lines of self.workspace / self.model / etc.
        self.workspace = config.workspace
        self.model = config.model
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        self.max_iterations = config.max_iterations
        self.restrict_to_workspace = config.restrict_to_workspace
        self.brave_api_key = config.brave_api_key
        self.exec_config = config.exec_config
        self.role_name = config.role_name

        # Mutable per-session state
        self.delegation_count: int = 0
        # Per-session delegation budget — raises _CycleError when exhausted (LAN-121/132).
        # This is a structural hard cap enforced in dispatch(), not an advisory prompt nudge.
        # Distinct from MAX_DELEGATION_DEPTH which caps the ancestry chain length.
        self.max_delegations: int = max_delegation_depth
        self.routing_trace: deque[dict[str, Any]] = deque(maxlen=1000)

        self.coordinator: Coordinator | None = coordinator
        self.scratchpad: Scratchpad | None = scratchpad
        self.active_messages: list[dict[str, Any]] | None = active_messages
        self.tools: ToolExecutor | None = tools
        self.mcp_tools: list[Tool] = mcp_tools if mcp_tools is not None else []
        self.on_progress: ProgressCallback | None = on_progress
        # JSONL persistence for routing trace (LAN-130). Set by loop._ensure_scratchpad.
        self._trace_path: Path | None = None

        # Pre-built stateless tool instances — shared across delegations to avoid
        # per-call object construction overhead (LAN-138).
        _allowed_dir = self.workspace if self.restrict_to_workspace else None
        _tools: list[Tool] = [
            ReadFileTool(workspace=self.workspace, allowed_dir=_allowed_dir),
            ListDirTool(workspace=self.workspace, allowed_dir=_allowed_dir),
            WriteFileTool(workspace=self.workspace, allowed_dir=_allowed_dir),
            EditFileTool(workspace=self.workspace, allowed_dir=_allowed_dir),
        ]
        if self.exec_config is not None:
            _tools.append(
                ExecTool(
                    working_dir=str(self.workspace),
                    timeout=self.exec_config.timeout,
                    restrict_to_workspace=self.restrict_to_workspace,
                    shell_mode=self.exec_config.shell_mode,
                )
            )
        _tools.extend([WebSearchTool(api_key=self.brave_api_key), WebFetchTool()])
        self._cached_tools: dict[str, Tool] = {t.name: t for t in _tools}

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def wire_delegate_tools(
        self,
        available_roles_fn: Callable[[], list[str]] | None = None,
    ) -> None:
        """Set the dispatch callback on all registered delegate tools.

        Parameters
        ----------
        available_roles_fn:
            Optional callback returning known role names for pre-dispatch
            validation (Phase D).
        """
        if not self.tools:
            return
        for name in ("delegate", "delegate_parallel"):
            tool = self.tools.get(name)
            if isinstance(tool, DelegateTool | DelegateParallelTool):
                tool.set_dispatch(self.dispatch)
                if available_roles_fn is not None:
                    tool.set_available_roles_fn(available_roles_fn)

    # ------------------------------------------------------------------
    # Tracing
    # ------------------------------------------------------------------

    def record_route_trace(
        self,
        event: str,
        *,
        role: str = "",
        confidence: float = 0.0,
        latency_ms: float = 0.0,
        from_role: str = "",
        depth: int = 0,
        success: bool = True,
        message_excerpt: str = "",
        tools_used: list[str] | None = None,
    ) -> None:
        """Append an entry to the in-memory routing trace and record metrics."""
        entry: dict[str, Any] = {
            "event": event,
            "role": role,
            "confidence": confidence,
            "latency_ms": round(latency_ms, 3),
            "from_role": from_role,
            "depth": depth,
            "success": success,
            "message": sanitize_for_trace(message_excerpt[:80]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if tools_used is not None:
            entry["tools_used"] = tools_used
            entry["tools_used_count"] = len(tools_used)
        self.routing_trace.append(entry)
        if self._trace_path is not None:
            try:
                self._trace_path.parent.mkdir(parents=True, exist_ok=True)
                with self._trace_path.open("a", encoding="utf-8") as _fh:
                    _fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                logger.warning("Failed to persist route trace to {}", self._trace_path)

    def get_routing_trace(self) -> list[dict[str, Any]]:
        """Return a copy of the routing trace."""
        return list(self.routing_trace)

    # ------------------------------------------------------------------
    # Dispatch entry point
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        target_role: str,
        task: str,
        context: str | None,
    ) -> DelegationResult:
        """Route a delegated sub-task through the coordinator and execute it."""
        if not self.coordinator:
            raise NanobotError("Coordinator not available for delegation")

        # Resolve role
        role: AgentRoleConfig | None = None
        if target_role:
            role = self.coordinator.route_direct(target_role)
        if role is None:
            role = await self.coordinator.route(task)

        # Session budget guard — hard cap on total delegations (LAN-121).
        max_del = getattr(self, "max_delegations", 8)
        if self.delegation_count >= max_del:
            raise _CycleError(
                f"Delegation budget exhausted: {self.delegation_count}/{max_del} "
                "delegations used this session"
            )

        # Depth and cycle guard
        ancestry = _delegation_ancestry.get()
        depth = len(ancestry)
        if depth >= MAX_DELEGATION_DEPTH:
            chain = " → ".join((*ancestry, role.name))
            self.record_route_trace(
                "delegate_depth_blocked",
                role=role.name,
                from_role=ancestry[-1] if ancestry else "",
                depth=depth,
                success=False,
                message_excerpt=task,
            )
            raise _CycleError(f"Maximum delegation depth ({MAX_DELEGATION_DEPTH}) reached: {chain}")
        if role.name in ancestry:
            chain = " → ".join((*ancestry, role.name))
            self.record_route_trace(
                "delegate_cycle_blocked",
                role=role.name,
                from_role=ancestry[-1] if ancestry else "",
                depth=depth,
                success=False,
                message_excerpt=task,
            )
            raise _CycleError(f"Delegation cycle detected: {chain}")

        from_role = ancestry[-1] if ancestry else self.role_name
        self.record_route_trace(
            "delegate",
            role=role.name,
            from_role=from_role,
            depth=depth,
            message_excerpt=task,
        )

        # Increment atomically before any await so parallel dispatches under
        # asyncio.gather each get a unique ID (LAN-117).
        self.delegation_count += 1
        delegation_id = f"del_{self.delegation_count:03d}"

        # Emit canonical delegation start event if a progress callback is wired.
        if self.on_progress:
            try:
                await self.on_progress(
                    DelegateStartEvent(
                        delegation_id=delegation_id,
                        child_role=role.name,
                        task_title=task[:120],
                    )
                )
            except Exception as exc:  # crash-barrier: never let event emission block delegation
                logger.debug("delegate_start event emission failed: {}", exc)

        t0 = time.monotonic()
        token = _delegation_ancestry.set((*ancestry, role.name))
        try:
            async with langfuse_span(
                name="delegate",
                input=sanitize_for_trace(task[:200]),
                metadata={
                    "target_role": role.name,
                    "from_role": from_role,
                    "depth": str(depth),
                },
            ):
                result, used_tools = await self.execute_delegated_agent(role, task, context)
            latency_ms = (time.monotonic() - t0) * 1000
            delegation_total.labels(from_role=from_role, to_role=role.name, success="true").inc()
            delegation_latency_seconds.labels(to_role=role.name).observe(latency_ms / 1000)
            self.record_route_trace(
                "delegate_complete",
                role=role.name,
                latency_ms=latency_ms,
                depth=depth,
                success=True,
                message_excerpt=task,
                tools_used=used_tools,
            )
            # Emit canonical delegation end event.
            if self.on_progress:
                try:
                    await self.on_progress(
                        DelegateEndEvent(delegation_id=delegation_id, success=True)
                    )
                except Exception as exc:  # crash-barrier: never let event emission block delegation
                    logger.debug("delegate_end event emission failed: {}", exc)
            return DelegationResult(content=result, tools_used=used_tools)
        except Exception:  # crash-barrier: delegation must record trace on any error
            latency_ms = (time.monotonic() - t0) * 1000
            delegation_total.labels(from_role=from_role, to_role=role.name, success="false").inc()
            delegation_latency_seconds.labels(to_role=role.name).observe(latency_ms / 1000)
            self.record_route_trace(
                "delegate_complete",
                role=role.name,
                latency_ms=latency_ms,
                depth=depth,
                success=False,
                message_excerpt=task,
            )
            if self.on_progress:
                try:
                    await self.on_progress(
                        DelegateEndEvent(delegation_id=delegation_id, success=False)
                    )
                except Exception as exc:  # crash-barrier: never let event emission block delegation
                    logger.debug("delegate_end (failure) event emission failed: {}", exc)
            raise
        finally:
            _delegation_ancestry.reset(token)

    # ------------------------------------------------------------------
    # Delegated agent execution
    # ------------------------------------------------------------------

    async def execute_delegated_agent(
        self,
        role: AgentRoleConfig,
        task: str,
        context: str | None,
    ) -> tuple[str, list[str]]:
        """Set up and run a delegated agent for a single sub-task.

        Returns ``(summary, tools_used)``.
        """
        task_type = classify_task_type(role.name, task)
        logger.debug("Delegation task type: {} (role={})", task_type, role.name)

        # Build isolated tool set.
        # Privileged tools (exec, write, edit, re-delegation) are default-denied
        # for delegated agents; only granted when the role's allowed_tools list
        # explicitly includes them.  This prevents a compromised or misbehaving
        # sub-agent from running shell commands or further delegating without an
        # explicit config grant.
        _explicit_grant: set[str] = (
            set(role.allowed_tools) if role.allowed_tools is not None else set()
        )
        _explicit_deny: set[str] = set(role.denied_tools) if role.denied_tools else set()
        _no_explicit_allowlist = role.allowed_tools is None
        _delegated_privilege = frozenset({"exec", "write_file", "edit_file", "delegate"})

        def _grant(name: str) -> bool:
            """True when the tool should be included in the delegated tool set."""
            if name in _explicit_deny:
                return False
            if name in _delegated_privilege:
                # Privileged tools require an explicit allowlist grant.
                return not _no_explicit_allowlist and name in _explicit_grant
            if not _no_explicit_allowlist:
                return name in _explicit_grant
            return True

        tools = ToolRegistry()

        # Register pre-cached stateless tool instances (LAN-138); grant() filters
        # by role allowed/denied lists.  Privileged tools (exec, write_file,
        # edit_file) are blocked by _grant() unless explicitly in allowed_tools.
        # Web tools respect denied_tools config (LAN-118); shell_mode forwarded
        # to ExecTool via the cached instance (LAN-120).
        for _t in self._cached_tools.values():
            if _grant(_t.name):
                tools.register(_t)

        # Re-delegation — privileged
        child_delegate = DelegateTool()
        child_delegate.set_dispatch(self.dispatch)
        if _grant(child_delegate.name):
            tools.register(child_delegate)

        # MCP tools (shared instances, injected by AgentLoop)
        for tool in self.mcp_tools:
            if _grant(tool.name):
                tools.register(tool)

        # Build delegation contract
        user_content, output_schema = build_delegation_contract(
            role=role.name,
            task=task,
            context=context,
            task_type=task_type,
            workspace=self.workspace,
            active_messages=list(self.active_messages) if self.active_messages else [],
            scratchpad=self.scratchpad,
        )

        # Inject scratchpad for all delegated agents so prior findings are visible.
        # Previously restricted to pm/writing/general; code and research agents now
        # also receive prior results to avoid re-searching facts already discovered
        # by peers in the same delegation chain (LAN-112).
        if self.scratchpad:
            scratchpad_content = self.scratchpad.read()
            if scratchpad_content and scratchpad_content != "Scratchpad is empty.":
                user_content += (
                    "\n\n## Prior Agent Findings (Scratchpad)\n"
                    + _cap_scratchpad_for_injection(scratchpad_content)
                )

        # Build system prompt
        avail_tools = ", ".join(tools.tool_names)
        system_prompt = prompts.render(
            "delegation_agent",
            role_name=role.name,
            role_prompt=role.system_prompt or "",
            avail_tools=avail_tools,
            output_schema=output_schema,
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        # Hard iteration cap for delegated agents (LAN-109).
        # Without this cap, nested delegation trees multiply LLM cost exponentially:
        # parent (40 iters) × child (40 iters) = up to 1,600 calls per turn.
        # Synthesis tasks need fewer iterations; investigation tasks get more.
        if task_type in ("report_writing", "general"):
            iter_cap = 8
        else:
            iter_cap = 12
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

        # Retry if agent didn't use any tools on an investigation-type task
        if not tools_used and task_type not in ("report_writing",) and max_iter > 2:
            logger.warning(
                "Delegated {} agent used no tools — retrying with tool-use reminder",
                role.name,
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

        # Write to scratchpad if available
        if self.scratchpad:
            grounded = len(tools_used) > 0
            await self.scratchpad.write(
                role=role.name,
                label=task[:80],
                content=summary,
                metadata={"grounded": grounded, "tools_used": tools_used},
            )

        return summary, tools_used
