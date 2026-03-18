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
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.observability import span as langfuse_span
from nanobot.agent.tool_loop import run_tool_loop
from nanobot.agent.tools.base import ToolResult  # noqa: F401 — re-export for tests
from nanobot.agent.tools.delegate import (
    DelegateParallelTool,
    DelegateTool,
    DelegationResult,
    _CycleError,
)
from nanobot.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.config.schema import AgentRoleConfig

if TYPE_CHECKING:
    from nanobot.agent.coordinator import Coordinator
    from nanobot.agent.scratchpad import Scratchpad
    from nanobot.agent.tool_executor import ToolExecutor
    from nanobot.agent.tools.base import Tool
    from nanobot.config.schema import ExecToolConfig
    from nanobot.providers.base import LLMProvider

# Per-coroutine delegation ancestry — isolated across asyncio.gather branches.
_delegation_ancestry: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "_delegation_ancestry", default=()
)

# Maximum number of distinct roles that may be chained in a single delegation path.
# Prevents runaway recursive delegation: each level runs up to max_iterations LLM
# calls, so uncapped chains multiply cost exponentially.
MAX_DELEGATION_DEPTH: int = 3

# ---------------------------------------------------------------------------
# Task type taxonomy
# ---------------------------------------------------------------------------

TASK_TYPES: dict[str, dict[str, Any]] = {
    "local_code_analysis": {
        "prefer": ["read_file", "list_dir", "exec"],
        "avoid_first": ["web_search", "web_fetch"],
        "evidence": "file paths + code excerpts with line numbers",
        "completion": (
            "Stop when you have inspected the relevant files and can answer "
            "the question with evidence. Do not exhaustively scan every file "
            "unless the task explicitly asks for it."
        ),
        "anti_hallucination": (
            "Do not infer architecture from naming alone. "
            "Distinguish inspected evidence vs assumption. "
            "Say 'not found' when absent. Cite inspected file paths."
        ),
    },
    "repo_architecture": {
        "prefer": ["read_file", "list_dir", "exec"],
        "avoid_first": ["web_search"],
        "evidence": "file paths, module relationships, code excerpts",
        "completion": (
            "Stop when you have mapped the relevant module structure "
            "and key interfaces. Focus on structure, not every detail."
        ),
        "anti_hallucination": (
            "Only describe architecture you have verified by reading files. "
            "Do not infer from file names alone. Cite every claim."
        ),
    },
    "web_research": {
        "prefer": ["web_search", "web_fetch"],
        "avoid_first": ["exec", "write_file"],
        "evidence": "URLs, quoted excerpts, publication dates",
        "completion": (
            "Stop after finding 3-5 high-quality sources that answer "
            "the question. Cross-reference when possible."
        ),
        "anti_hallucination": (
            "Cite URLs for every claim. Distinguish search results from "
            "your own analysis. Say 'no results found' when searches fail."
        ),
    },
    "report_writing": {
        "prefer": ["write_file", "read_file"],
        "avoid_first": ["exec", "web_search"],
        "evidence": "references to source findings from other agents",
        "completion": (
            "Stop after producing the requested document. Base all content on prior agent findings."
        ),
        "anti_hallucination": (
            "Use ONLY data from prior agent findings (scratchpad). "
            "Do not invent statistics, metrics, or file paths. "
            "If data is missing, note it as a gap."
        ),
    },
    "bug_investigation": {
        "prefer": ["read_file", "exec", "list_dir"],
        "avoid_first": ["web_search", "write_file"],
        "evidence": "error messages, stack traces, file paths + line numbers",
        "completion": (
            "Stop when you have identified the root cause with evidence, "
            "or when you have exhausted reasonable investigation paths."
        ),
        "anti_hallucination": (
            "Report only errors and behavior you have observed via tools. "
            "Do not guess root causes without evidence."
        ),
    },
    "general": {
        "prefer": [],
        "avoid_first": [],
        "evidence": "tool output excerpts",
        "completion": "Stop when the task objective is met.",
        "anti_hallucination": ("Ground all claims in tool output. Say 'unknown' when unsure."),
    },
}


class DelegationDispatcher:
    """Manages delegation routing, contract construction, execution, and tracing."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        workspace: Path,
        model: str,
        temperature: float,
        max_tokens: int,
        max_iterations: int,
        restrict_to_workspace: bool,
        brave_api_key: str | None,
        exec_config: ExecToolConfig,
        role_name: str,
    ) -> None:
        self.provider = provider
        self.workspace = workspace
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations
        self.restrict_to_workspace = restrict_to_workspace
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config
        self.role_name = role_name

        # Mutable per-session state
        self.delegation_count: int = 0
        self.max_delegations: int = 8
        self.routing_trace: list[dict[str, Any]] = []

        # Set by AgentLoop after construction
        self.coordinator: Coordinator | None = None
        self.scratchpad: Scratchpad | None = None
        self.active_messages: list[dict[str, Any]] | None = None
        self.tools: ToolExecutor | None = None  # for wire_delegate_tools
        # MCP tools injected lazily by AgentLoop after _connect_mcp()
        self.mcp_tools: list[Tool] = []
        # Per-turn progress callback — set by AgentLoop._process_message, cleared after turn.
        self.on_progress: Callable[..., Awaitable[None]] | None = None

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
            if isinstance(tool, (DelegateTool, DelegateParallelTool)):
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
            "message": message_excerpt[:80],
            "timestamp": datetime.now().isoformat(),
        }
        if tools_used is not None:
            entry["tools_used"] = tools_used
            entry["tools_used_count"] = len(tools_used)
        self.routing_trace.append(entry)

    def get_routing_trace(self) -> list[dict[str, Any]]:
        """Return a copy of the routing trace."""
        return list(self.routing_trace)

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def gather_recent_tool_results(self, max_results: int = 15, max_chars: int = 8000) -> str:
        """Extract recent tool results from the active message list."""
        if not self.active_messages:
            return ""
        tool_results: list[str] = []
        total_chars = 0
        for m in reversed(self.active_messages):
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

    def extract_plan_text(self) -> str:
        """Pull the plan from active_messages if planning was triggered."""
        if not self.active_messages:
            return ""
        found_plan_prompt = False
        for m in self.active_messages:
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

    def extract_user_request(self) -> str:
        """Pull the original user message from active_messages."""
        if not self.active_messages:
            return ""
        for m in self.active_messages:
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str):
                    return content.strip()
        return ""

    def build_execution_context(self, task_type: str) -> str:
        """Assemble project knowledge with tier-based stratification."""
        parts: list[str] = [f"Workspace: {self.workspace}"]
        try:
            entries = sorted(self.workspace.iterdir())
            tree_lines = []
            for entry in entries[:50]:
                suffix = "/" if entry.is_dir() else ""
                tree_lines.append(f"  {entry.name}{suffix}")
            if tree_lines:
                parts.append("Directory layout:\n" + "\n".join(tree_lines))
        except OSError:
            pass
        if task_type in ("local_code_analysis", "repo_architecture", "bug_investigation"):
            for name in ("AGENTS.md", "README.md", "SOUL.md"):
                path = self.workspace / name
                try:
                    if path.is_file():
                        text = path.read_text(encoding="utf-8", errors="replace")[:1500]
                        if text.strip():
                            parts.append(f"--- {name} (excerpt) ---\n{text.strip()}")
                except OSError:
                    pass
        return "\n\n".join(parts)

    def build_parallel_work_summary(self, role: str) -> str:
        """Build a brief summary of what other agents are doing."""
        if not self.scratchpad:
            return ""
        entries = self.scratchpad.list_entries()
        if not entries:
            return ""
        lines: list[str] = []
        for e in entries:
            if e.get("role") == role:
                continue
            lines.append(f"- [{e.get('role', '?')}] {e.get('label', '')[:60]}")
        return "\n".join(lines) if lines else ""

    # ------------------------------------------------------------------
    # Task classification
    # ------------------------------------------------------------------

    @staticmethod
    def classify_task_type(role: str, task: str) -> str:
        """Classify a delegation task into a task type from the taxonomy."""
        task_lower = task.lower()
        if role == "writing":
            return "report_writing"
        code_signals = (
            "code",
            "module",
            "file",
            "function",
            "class",
            "test",
            "import",
            "line",
            "bug",
            "error",
            "refactor",
            "implement",
            "source",
            "python",
            ".py",
            "coverage",
            "lint",
            "scan",
        )
        bug_signals = ("bug", "error", "crash", "fail", "exception", "broken", "fix")
        web_signals = (
            "latest",
            "current",
            "news",
            "trend",
            "benchmark",
            "compare with",
            "industry",
            "best practice",
            "state of the art",
        )
        arch_signals = (
            "architecture",
            "subsystem",
            "design",
            "structure",
            "pattern",
            "how does",
            "relationship",
            "dependency",
        )
        project_signals = (
            "our",
            "this project",
            "nanobot",
            "workspace",
            "codebase",
        )
        if role == "code" and any(s in task_lower for s in bug_signals):
            return "bug_investigation"
        if any(s in task_lower for s in arch_signals):
            return "repo_architecture"
        if any(s in task_lower for s in code_signals) or role == "code":
            return "local_code_analysis"
        if any(s in task_lower for s in web_signals):
            if not any(s in task_lower for s in project_signals):
                return "web_research"
            return "repo_architecture"
        if role == "research":
            if any(s in task_lower for s in project_signals):
                return "repo_architecture"
            return "web_research"
        return "general"

    @staticmethod
    def has_parallel_structure(text: str) -> bool:
        """Detect enumerated independent subtasks in the user message."""
        text_lower = text.strip().lower()
        count_words = re.search(
            r"\b(two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
            r"(areas?|parts?|aspects?|sections?|components?|topics?|items?|tasks?"
            r"|dimensions?|categories?|modules?|files?|layers?)",
            text_lower,
        )
        if count_words:
            return True
        enum_pattern = re.search(r"(?:[^,]+,\s*){2,}(?:and|&)\s+[^,.]+", text_lower)
        if enum_pattern:
            return True
        colon_list = re.search(r":\s*[^,]+(?:,\s*[^,]+){2,}", text_lower)
        if colon_list:
            return True
        numbered = re.findall(r"(?:^|\s)(?:\d+[.)\]]|[a-z][.)\]])\s", text_lower)
        if len(numbered) >= 3:
            return True
        across_pattern = re.search(r"\bacross\b.+,.+(?:,|and)\s+", text_lower)
        if across_pattern:
            return True
        return False

    # ------------------------------------------------------------------
    # Delegation contract
    # ------------------------------------------------------------------

    def build_delegation_contract(
        self,
        role: str,
        task: str,
        context: str | None,
        task_type: str,
    ) -> tuple[str, str]:
        """Build a typed delegation contract.

        Returns ``(user_content, output_schema_instruction)``.
        """
        tt = TASK_TYPES.get(task_type, TASK_TYPES["general"])
        sections: list[str] = []

        # --- Tier A: always present ---
        user_request = self.extract_user_request()
        if user_request:
            sections.append(f"## Original User Request\n{user_request}")
        sections.append(f"## Your Mission\n{task}")
        if context:
            sections.append(f"### Additional Context\n{context}")
        sections.append(f"## Project Root\n`{self.workspace}`")

        non_goals: list[str] = []
        avoid = tt.get("avoid_first", [])
        if avoid:
            non_goals.append(f"Do not start with: {', '.join(avoid)}")
        parallel = self.build_parallel_work_summary(role)
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
        plan_text = self.extract_plan_text()
        if plan_text:
            sections.append(f"## Overall Plan (for context)\n{plan_text}")
        execution_ctx = self.build_execution_context(task_type)
        if execution_ctx:
            sections.append(f"## Project Context\n{execution_ctx}")
        parent_findings = self.gather_recent_tool_results()
        if parent_findings:
            sections.append(f"## Prior Results\n{parent_findings}")

        evidence_type = tt.get("evidence", "tool output excerpts")
        output_schema = (
            "\n\nYour response MUST use this structure:\n"
            "## Findings\n<your key findings>\n\n"
            "## Evidence\n<supporting evidence: " + evidence_type + ">\n\n"
            "## Open Questions\n<anything unresolved or needing further investigation>\n\n"
            "## Confidence\n<high/medium/low with brief justification>\n\n"
            "## Files Inspected\n<list of files/sources you actually examined>"
        )

        return "\n\n".join(sections), output_schema

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
            raise RuntimeError("Coordinator not available for delegation")

        # Resolve role
        role: AgentRoleConfig | None = None
        if target_role:
            role = self.coordinator.route_direct(target_role)
        if role is None:
            role = await self.coordinator.route(task)

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

        delegation_id = f"del_{self.delegation_count + 1:03d}"

        # Emit canonical delegation start event if a progress callback is wired.
        if self.on_progress:
            try:
                await self.on_progress(
                    "",
                    delegate_start={
                        "delegation_id": delegation_id,
                        "child_role": role.name,
                        "task_title": task[:120],
                    },
                )
            except Exception:  # crash-barrier: never let event emission block delegation
                pass

        t0 = time.monotonic()
        self.delegation_count += 1
        token = _delegation_ancestry.set((*ancestry, role.name))
        try:
            async with langfuse_span(
                name="delegate",
                input=task[:200],
                metadata={
                    "target_role": role.name,
                    "from_role": from_role,
                    "depth": str(depth),
                },
            ):
                result, used_tools = await self.execute_delegated_agent(role, task, context)
            latency_ms = (time.monotonic() - t0) * 1000
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
                        "",
                        delegate_end={
                            "delegation_id": delegation_id,
                            "success": True,
                        },
                    )
                except Exception:  # crash-barrier: never let event emission block delegation
                    pass
            return DelegationResult(content=result, tools_used=used_tools)
        except Exception:  # crash-barrier: delegation must record trace on any error
            latency_ms = (time.monotonic() - t0) * 1000
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
                        "",
                        delegate_end={
                            "delegation_id": delegation_id,
                            "success": False,
                        },
                    )
                except Exception:  # crash-barrier: never let event emission block delegation
                    pass
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
        task_type = self.classify_task_type(role.name, task)
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
        allowed_dir = self.workspace if self.restrict_to_workspace else None

        # Read-only filesystem tools always considered (grant() decides inclusion)
        for ro_cls in (ReadFileTool, ListDirTool):
            ro_t = ro_cls(workspace=self.workspace, allowed_dir=allowed_dir)
            if _grant(ro_t.name):
                tools.register(ro_t)

        # Write filesystem tools — privileged
        for rw_cls in (WriteFileTool, EditFileTool):
            rw_t = rw_cls(workspace=self.workspace, allowed_dir=allowed_dir)
            if _grant(rw_t.name):
                tools.register(rw_t)

        # Exec — privileged
        exec_t = ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        )
        if _grant(exec_t.name):
            tools.register(exec_t)

        tools.register(WebSearchTool(api_key=self.brave_api_key))
        tools.register(WebFetchTool())

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
        user_content, output_schema = self.build_delegation_contract(
            role=role.name,
            task=task,
            context=context,
            task_type=task_type,
        )

        # For synthesizing roles, inject scratchpad as primary input
        if role.name in ("pm", "writing", "general") and self.scratchpad:
            scratchpad_content = self.scratchpad.read()
            if scratchpad_content and scratchpad_content != "Scratchpad is empty.":
                user_content += f"\n\n## Prior Agent Findings (Scratchpad)\n{scratchpad_content}"

        # Build system prompt
        avail_tools = ", ".join(tools.tool_names)
        system_prompt = (
            f"You are the **{role.name}** specialist agent.\n\n"
            f"{role.system_prompt or ''}\n\n"
            f"You MUST use your available tools to complete this task. "
            f"Do NOT fabricate information — always verify with tools first."
        )
        if avail_tools:
            system_prompt += f"\nAvailable tools: {avail_tools}"
        system_prompt += output_schema

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

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
