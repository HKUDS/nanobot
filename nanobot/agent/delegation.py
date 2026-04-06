"""Scoped subagent delegation: waves, parallel runs, structured results.

Complements :class:`nanobot.agent.subagent.SubagentManager` (background spawn).
This module is for in-process orchestration with :class:`ContextCompactor`.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.compactor import ContextCompactor, estimate_tokens
from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.search import GlobTool, GrepTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.config.schema import ExecToolConfig, WebToolsConfig
from nanobot.providers.base import LLMProvider


class SubagentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MergeStrategy(str, Enum):
    APPEND = "append"
    PATCH = "patch"
    REDUCE = "reduce"
    GATE = "gate"


@dataclass
class FileScope:
    """Glob patterns for readable / writable paths (workspace-relative)."""

    readable: list[str] = field(default_factory=list)
    writable: list[str] = field(default_factory=list)

    def can_read(self, path: str) -> bool:
        return self._matches(path, self.readable)

    def can_write(self, path: str) -> bool:
        return self._matches(path, self.writable)

    def _matches(self, path: str, patterns: list[str]) -> bool:
        import fnmatch

        norm = path.replace("\\", "/").lstrip("/")
        return any(fnmatch.fnmatch(norm, p) for p in patterns)


@dataclass
class SubagentTask:
    """One delegated unit of work."""

    objective: str
    context_slice: str = ""
    file_contents: dict[str, str] = field(default_factory=dict)
    scope: FileScope = field(default_factory=FileScope)
    merge_strategy: MergeStrategy = MergeStrategy.PATCH
    depends_on: list[str] = field(default_factory=list)
    max_turns: int = 15
    budget_tokens: int = 40_000
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            digest = hashlib.sha256(self.objective.encode()).hexdigest()[:8]
            self.id = f"sub_{digest}"


@dataclass
class SubagentResult:
    """Structured output from a scoped subagent run."""

    task_id: str
    status: SubagentStatus
    summary: str
    file_changes: dict[str, str] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    error: str | None = None
    tokens_used: int = 0
    turns_used: int = 0
    wall_time_seconds: float = 0.0


@dataclass
class DelegationPlan:
    """Tasks grouped into sequential waves; tasks in a wave may run in parallel."""

    waves: list[list[SubagentTask]]
    rationale: str = ""
    estimated_total_tokens: int = 0

    def all_tasks(self) -> list[SubagentTask]:
        return [t for wave in self.waves for t in wave]

    def task_count(self) -> int:
        return sum(len(w) for w in self.waves)


@dataclass
class MergeReport:
    """Merged file changes with conflict notes."""

    file_changes: dict[str, str]
    conflicts: list[str]
    observations: list[str]
    success: bool

    def summary(self) -> str:
        parts = [f"Modified {len(self.file_changes)} files."]
        if self.conflicts:
            parts.append(f"{len(self.conflicts)} conflicts detected.")
        if self.observations:
            parts.append(f"{len(self.observations)} observations from subagents.")
        return " ".join(parts)


class ContextIsolator:
    """Build a minimal system prompt bundle for a subagent."""

    SUBAGENT_SYSTEM_PROMPT = (
        "You are a focused coding subagent. You have been given a specific task "
        "by a parent agent. Complete ONLY the described task. Do not explore "
        "beyond your file scope. Do not ask questions — make reasonable decisions "
        "and document your assumptions in observations.\n\n"
        "When finished, output a structured result with:\n"
        "1. A one-paragraph summary of what you did\n"
        "2. The complete contents of any files you modified\n"
        "3. Any observations the parent agent should know about\n"
    )

    @staticmethod
    def build_context(task: SubagentTask) -> str:
        sections: list[str] = []
        sections.append(f"<system>\n{ContextIsolator.SUBAGENT_SYSTEM_PROMPT}</system>")
        sections.append(f"<task>\n{task.objective}\n</task>")
        if task.context_slice.strip():
            sections.append(
                f"<parent_context>\n{task.context_slice.strip()}\n</parent_context>",
            )
        if task.file_contents:
            file_parts = [
                f"### {path}\n```\n{content}\n```"
                for path, content in task.file_contents.items()
            ]
            sections.append("<files>\n" + "\n\n".join(file_parts) + "\n</files>")
        scope_desc = (
            f"Readable: {', '.join(task.scope.readable) or 'none'}\n"
            f"Writable: {', '.join(task.scope.writable) or 'none (read-only)'}"
        )
        sections.append(f"<scope>\n{scope_desc}\n</scope>")
        context = "\n\n".join(sections)
        tokens = estimate_tokens(context)
        if tokens > task.budget_tokens:
            return ContextIsolator._trim_to_budget(context, task.budget_tokens)
        return context

    @staticmethod
    def _trim_to_budget(context: str, budget: int) -> str:
        target_chars = int(budget * 3.5)
        if len(context) <= target_chars:
            return context
        files_start = context.find("<files>")
        files_end = context.find("</files>")
        if files_start == -1 or files_end == -1:
            return context[:target_chars]
        before = context[:files_start]
        after = context[files_end:]
        available = target_chars - len(before) - len(after)
        files_section = context[files_start : files_end + len("</files>")]
        if available > 0 and available < len(files_section):
            half = available // 2
            files_section = (
                files_section[:half]
                + "\n\n... [truncated for budget] ...\n\n"
                + files_section[-half:]
            )
        return before + files_section + after


class _PathCaptureHook(AgentHook):
    """Record tool paths for post-run file snapshotting."""

    def __init__(self) -> None:
        self.write_paths: list[str] = []

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tc in context.tool_calls:
            if tc.name in ("write_file", "edit_file"):
                path = tc.arguments.get("path")
                if isinstance(path, str) and path:
                    self.write_paths.append(path)


class _ScopedReadFile(ReadFileTool):
    def __init__(self, *args: Any, scope: FileScope, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._delegation_scope = scope

    async def execute(self, path: str | None = None, **kwargs: Any) -> Any:
        if path and not self._delegation_scope.can_read(path):
            return (
                f"Error: path {path} is outside readable scope "
                f"({self._delegation_scope.readable})."
            )
        return await super().execute(path=path, **kwargs)


class _ScopedWriteFile(WriteFileTool):
    def __init__(self, *args: Any, scope: FileScope, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._delegation_scope = scope

    async def execute(self, **kwargs: Any) -> Any:
        path = kwargs.get("path")
        if path and not self._delegation_scope.can_write(str(path)):
            return (
                f"Error: path {path} is outside writable scope "
                f"({self._delegation_scope.writable})."
            )
        return await super().execute(**kwargs)


class _ScopedEditFile(EditFileTool):
    def __init__(self, *args: Any, scope: FileScope, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._delegation_scope = scope

    async def execute(self, **kwargs: Any) -> Any:
        path = kwargs.get("path")
        if path and not self._delegation_scope.can_write(str(path)):
            return (
                f"Error: path {path} is outside writable scope "
                f"({self._delegation_scope.writable})."
            )
        return await super().execute(**kwargs)


def _build_task_tools(
    workspace: Path,
    scope: FileScope,
    *,
    allowed_dir: Path | None,
    extra_read: list[Path] | None,
    exec_config: ExecToolConfig,
    web_config: WebToolsConfig,
    restrict_to_workspace: bool,
) -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(
        _ScopedReadFile(
            workspace=workspace,
            allowed_dir=allowed_dir,
            extra_allowed_dirs=extra_read,
            scope=scope,
        ),
    )
    tools.register(
        _ScopedWriteFile(workspace=workspace, allowed_dir=allowed_dir, scope=scope),
    )
    tools.register(
        _ScopedEditFile(workspace=workspace, allowed_dir=allowed_dir, scope=scope),
    )
    tools.register(ListDirTool(workspace=workspace, allowed_dir=allowed_dir))
    tools.register(GlobTool(workspace=workspace, allowed_dir=allowed_dir))
    tools.register(GrepTool(workspace=workspace, allowed_dir=allowed_dir))
    if exec_config.enable:
        tools.register(
            ExecTool(
                working_dir=str(workspace),
                timeout=exec_config.timeout,
                restrict_to_workspace=restrict_to_workspace,
                sandbox=exec_config.sandbox,
                path_append=exec_config.path_append,
            ),
        )
    if web_config.enable:
        tools.register(
            WebSearchTool(config=web_config.search, proxy=web_config.proxy),
        )
        tools.register(WebFetchTool(proxy=web_config.proxy))
    return tools


def _snapshot_writes(workspace: Path, paths: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in paths:
        try:
            p = (workspace / rel).resolve()
            if p.is_file() and str(p).startswith(str(workspace.resolve())):
                out[rel] = p.read_text(encoding="utf-8")
        except OSError:
            logger.debug("Could not read {} for delegation snapshot", rel)
    return out


def _parse_final_summary(content: str | None) -> tuple[str, list[str]]:
    if not content:
        return "", []
    import re

    obs = re.findall(
        r"(?:observation|note|warning)[:\s]*(.+?)(?=\n|$)",
        content,
        re.I,
    )
    return content.strip()[:4000], [m.strip() for m in obs]


class ScopedDelegationRunner:
    """Run one :class:`SubagentTask` using :class:`AgentRunner` and scoped tools."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        model: str,
        max_tool_result_chars: int = 16_000,
        exec_config: ExecToolConfig | None = None,
        web_config: WebToolsConfig | None = None,
        restrict_to_workspace: bool = False,
        extra_read_dirs: list[Path] | None = None,
    ) -> None:
        self._provider = provider
        self._workspace = workspace
        self._model = model
        self._max_tool_result_chars = max_tool_result_chars
        self._exec_config = exec_config or ExecToolConfig()
        self._web_config = web_config or WebToolsConfig()
        self._restrict_to_workspace = restrict_to_workspace
        self._extra_read = extra_read_dirs
        self._runner = AgentRunner(provider)

    async def run(self, task: SubagentTask) -> SubagentResult:
        start = time.monotonic()
        allowed = (
            self._workspace
            if (self._restrict_to_workspace or self._exec_config.sandbox)
            else None
        )
        tools = _build_task_tools(
            self._workspace,
            task.scope,
            allowed_dir=allowed,
            extra_read=self._extra_read,
            exec_config=self._exec_config,
            web_config=self._web_config,
            restrict_to_workspace=self._restrict_to_workspace,
        )
        system = ContextIsolator.build_context(task)
        path_hook = _PathCaptureHook()
        spec = AgentRunSpec(
            initial_messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        "Complete the task using tools. When finished, reply with a "
                        "clear summary (no further tool calls)."
                    ),
                },
            ],
            tools=tools,
            model=self._model,
            max_iterations=task.max_turns,
            max_tool_result_chars=self._max_tool_result_chars,
            hook=path_hook,
            fail_on_tool_error=False,
            workspace=self._workspace,
        )
        try:
            result = await self._runner.run(spec)
        except Exception as exc:
            return SubagentResult(
                task_id=task.id,
                status=SubagentStatus.FAILED,
                summary=f"Runner error: {exc}",
                error=str(exc),
                wall_time_seconds=time.monotonic() - start,
            )

        summary, observations = _parse_final_summary(result.final_content)
        if not summary:
            summary = result.final_content or "(no summary)"
        file_changes = _snapshot_writes(self._workspace, path_hook.write_paths)
        turns = sum(
            1
            for m in result.messages
            if m.get("role") == "assistant" and m.get("tool_calls")
        ) + (1 if result.final_content else 0)

        status = SubagentStatus.COMPLETED
        err: str | None = None
        if result.stop_reason == "error":
            status = SubagentStatus.FAILED
            err = result.error or "error"
        elif result.stop_reason == "tool_error":
            status = SubagentStatus.FAILED
            err = result.error or "tool_error"

        return SubagentResult(
            task_id=task.id,
            status=status,
            summary=summary,
            file_changes=file_changes,
            observations=observations,
            error=err,
            tokens_used=result.usage.get("prompt_tokens", 0)
            + result.usage.get("completion_tokens", 0),
            turns_used=turns,
            wall_time_seconds=time.monotonic() - start,
        )


class SubagentOrchestrator:
    """Plan (heuristic) and execute delegated waves; push summaries into *compactor*."""

    def __init__(
        self,
        provider: LLMProvider,
        compactor: ContextCompactor,
        workspace: Path,
        model: str | None = None,
        max_concurrent: int = 4,
        max_tool_result_chars: int = 16_000,
        exec_config: ExecToolConfig | None = None,
        web_config: WebToolsConfig | None = None,
        restrict_to_workspace: bool = False,
    ) -> None:
        self._provider = provider
        self.compactor = compactor
        self._workspace = workspace
        self._model = model or provider.get_default_model()
        self._max_concurrent = max(1, max_concurrent)
        self._max_tool_result_chars = max_tool_result_chars
        self._exec_config = exec_config or ExecToolConfig()
        self._web_config = web_config or WebToolsConfig()
        self._restrict_to_workspace = restrict_to_workspace
        self._runner = ScopedDelegationRunner(
            provider=provider,
            workspace=workspace,
            model=self._model,
            max_tool_result_chars=max_tool_result_chars,
            exec_config=self._exec_config,
            web_config=self._web_config,
            restrict_to_workspace=restrict_to_workspace,
        )
        self.completed_results: list[SubagentResult] = []

    def plan_delegation(
        self,
        task_description: str,
        available_files: dict[str, str],
    ) -> DelegationPlan:
        """Heuristic single-wave plan: group files by directory."""
        paths = list(available_files.keys())
        groups: dict[str, list[str]] = {}
        for path in paths:
            dir_name = os.path.dirname(path) or "root"
            groups.setdefault(dir_name, []).append(path)

        parent_context = self.compactor.render()
        context_summary = self._extract_relevant_context(
            parent_context,
            task_description,
        )
        tasks: list[SubagentTask] = []
        for dir_name, group_paths in groups.items():
            safe_id = dir_name.replace("/", "_").replace(".", "_")
            file_contents = {p: available_files[p] for p in group_paths}
            tasks.append(
                SubagentTask(
                    id=f"sub_{safe_id}",
                    objective=(
                        f"{task_description}\n\nFocus on files under: {dir_name}"
                    ),
                    context_slice=context_summary,
                    file_contents=file_contents,
                    scope=FileScope(
                        readable=group_paths + ["*.md", "*.toml"],
                        writable=group_paths,
                    ),
                ),
            )
        est = sum(
            estimate_tokens(t.context_slice)
            + sum(estimate_tokens(c) for c in t.file_contents.values())
            for t in tasks
        )
        return DelegationPlan(
            waves=[tasks],
            rationale=f"Grouped {len(tasks)} tasks by directory.",
            estimated_total_tokens=est,
        )

    def _extract_relevant_context(self, full_context: str, task_description: str) -> str:
        task_words = set(task_description.lower().split())
        sections = full_context.split("\n\n")
        scored: list[tuple[int, str]] = []
        for section in sections:
            words = set(section.lower().split())
            overlap = len(task_words & words)
            if overlap > 0 or len(section) < 200:
                scored.append((overlap, section))
        scored.sort(key=lambda x: x[0], reverse=True)
        budget = 5000
        kept: list[str] = []
        used = 0
        for _score, section in scored:
            t = estimate_tokens(section)
            if used + t > budget:
                break
            kept.append(section)
            used += t
        return "\n\n".join(kept)

    async def execute(self, plan: DelegationPlan) -> list[SubagentResult]:
        all_results: list[SubagentResult] = []
        results_by_id: dict[str, SubagentResult] = {}

        for wave in plan.waves:
            for task in wave:
                if task.depends_on:
                    dep = self._build_dependency_context(
                        task.depends_on,
                        results_by_id,
                    )
                    task.context_slice = (
                        task.context_slice
                        + f"\n\n<dependency_results>\n{dep}\n</dependency_results>"
                    )

            wave_results = await self._execute_wave(wave)
            for res in wave_results:
                results_by_id[res.task_id] = res
                all_results.append(res)
                self.compactor.push(
                    "system",
                    f"[Subagent {res.task_id}] {res.status.value}: {res.summary[:1200]}",
                )

        self.completed_results.extend(all_results)
        return all_results

    async def _execute_wave(self, wave: list[SubagentTask]) -> list[SubagentResult]:
        sem = asyncio.Semaphore(self._max_concurrent)
        wave_sorted = sorted(wave, key=lambda t: t.priority, reverse=True)

        async def one(task: SubagentTask) -> SubagentResult:
            async with sem:
                return await self._runner.run(task)

        return await asyncio.gather(*[one(t) for t in wave_sorted])

    def _build_dependency_context(
        self,
        dep_ids: list[str],
        results: dict[str, SubagentResult],
    ) -> str:
        parts: list[str] = []
        for dep_id in dep_ids:
            res = results.get(dep_id)
            if not res:
                parts.append(f"[{dep_id}]: NOT COMPLETED")
                continue
            part = f"[{dep_id}] ({res.status.value}):\n{res.summary}"
            if res.observations:
                part += "\nObservations:\n" + "\n".join(
                    f"  - {o}" for o in res.observations
                )
            if res.file_changes:
                part += "\nModified files: " + ", ".join(res.file_changes.keys())
            parts.append(part)
        return "\n\n".join(parts)

    def merge_results(self, results: list[SubagentResult]) -> MergeReport:
        merged: dict[str, str] = {}
        conflicts: list[str] = []
        observations: list[str] = []
        for res in results:
            if res.status == SubagentStatus.FAILED:
                conflicts.append(f"Task {res.task_id} failed: {res.error}")
                continue
            for path, content in res.file_changes.items():
                if path in merged:
                    conflicts.append(
                        f"CONFLICT: {res.task_id} also modified {path}; "
                        f"keeping later version.",
                    )
                merged[path] = content
            observations.extend(res.observations)
        return MergeReport(
            file_changes=merged,
            conflicts=conflicts,
            observations=observations,
            success=len(conflicts) == 0,
        )
