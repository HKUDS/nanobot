## Why Subagents

The core problem: reading 15 files to understand a codebase uses ~60k tokens of context. If the agent then needs to edit 4 of those files, each edit requires reasoning about different concerns. Cramming all of that into one context window means the agent is reasoning about auth middleware while also trying to hold the database migration in working memory. Quality drops.

Claude Code's solution is to spawn scoped subagents — lightweight, isolated agent loops that inherit a focused slice of the parent's context, do one job, and return a structured result. The parent orchestrates; the children execute.

The three key properties: each subagent gets only the context it needs (isolation), multiple subagents can run at the same time (parallelism), and their results merge back into the parent cleanly (integration).

## The Architecture

```
Parent Agent (orchestrator)
├── understands the full plan
├── holds the compacted conversation context
├── decides what to delegate
│
├── Subagent A (edit auth.py)    ─┐
│   └── sees: auth.py, relevant  │
│       types, task description   │  concurrent
│                                 │
├── Subagent B (edit db.py)      ─┤
│   └── sees: db.py, schema,     │
│       migration notes           │
│                                 │
├── Subagent C (write tests)     ─┘
│   └── sees: test patterns,
│       API signatures from A+B
│
└── Merges results, resolves conflicts
```

## The Code

This goes in `nanobot/agent/subagent.py`:

```python
"""
Subagent spawning, context isolation, and parallel execution for nanobot.

Inspired by Claude Code's task delegation model: the parent agent decomposes
complex work into focused subtasks, each executed by an isolated subagent
with a minimal context window. Subagents can run concurrently, and their
results are merged back into the parent's context.

Key design decisions:
  - Subagents do NOT inherit the full parent conversation. They get a
    task brief, relevant file contents, and an optional context slice.
  - Each subagent has its own tool sandbox — it can read/write files,
    but only within its declared scope.
  - Parallelism is cooperative: the parent decides what can run
    concurrently based on dependency analysis.
  - Results are structured (not free-text), making merge deterministic.

Usage:
    orchestrator = SubagentOrchestrator(llm, tool_runner, compactor)
    plan = orchestrator.plan_delegation(task_description)
    results = await orchestrator.execute(plan)
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from nanobot.agent.compactor import ContextCompactor, estimate_tokens


# ── types ────────────────────────────────────────────────────────────────

class SubagentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MergeStrategy(Enum):
    """How the parent integrates subagent results."""
    APPEND = "append"             # just add to context (read-only tasks)
    PATCH = "patch"               # apply file diffs (edit tasks)
    REDUCE = "reduce"             # combine multiple results into one (analysis)
    GATE = "gate"                 # result determines whether to proceed (validation)


@dataclass
class FileScope:
    """Declares which files a subagent can see and/or modify."""
    readable: list[str] = field(default_factory=list)   # glob patterns
    writable: list[str] = field(default_factory=list)   # glob patterns

    def can_read(self, path: str) -> bool:
        return self._matches(path, self.readable)

    def can_write(self, path: str) -> bool:
        return self._matches(path, self.writable)

    def _matches(self, path: str, patterns: list[str]) -> bool:
        import fnmatch
        return any(fnmatch.fnmatch(path, p) for p in patterns)


@dataclass
class SubagentTask:
    """
    A self-contained task description for a subagent.

    The parent constructs these; each one becomes an isolated agent loop.
    """
    id: str
    objective: str                          # what the subagent should accomplish
    context_slice: str                      # relevant parent context (curated)
    file_contents: dict[str, str]           # path -> content, pre-loaded
    scope: FileScope                        # read/write permissions
    merge_strategy: MergeStrategy = MergeStrategy.PATCH
    depends_on: list[str] = field(default_factory=list)  # task IDs
    max_turns: int = 25                     # circuit breaker
    budget_tokens: int = 40_000             # context budget for this subagent
    priority: int = 0                       # higher = runs first in same wave
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            h = hashlib.sha256(self.objective.encode()).hexdigest()[:8]
            self.id = f"sub_{h}"


@dataclass
class SubagentResult:
    """Structured output from a completed subagent."""
    task_id: str
    status: SubagentStatus
    summary: str                            # human-readable summary of what was done
    file_changes: dict[str, str]            # path -> new content (full file)
    observations: list[str]                 # things the parent should know
    error: Optional[str] = None
    tokens_used: int = 0
    turns_used: int = 0
    wall_time_seconds: float = 0.0


@dataclass
class DelegationPlan:
    """
    The parent's plan for breaking a task into subagent work.

    Tasks are organized into waves — each wave contains tasks that can
    run in parallel. Waves execute sequentially.
    """
    waves: list[list[SubagentTask]]
    rationale: str                          # why this decomposition
    estimated_total_tokens: int = 0

    def all_tasks(self) -> list[SubagentTask]:
        return [t for wave in self.waves for t in wave]

    def task_count(self) -> int:
        return sum(len(w) for w in self.waves)


# ── context isolation ────────────────────────────────────────────────────

class ContextIsolator:
    """
    Builds the minimal context window for a subagent.

    The parent's full context might be 100k+ tokens. A subagent editing
    a single file needs maybe 15k. This class constructs that focused
    context, ensuring the subagent has everything it needs and nothing
    it doesn't.
    """

    # The subagent system prompt — much shorter than the parent's.
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
        """
        Assemble the isolated context for a subagent.

        Structure:
          - Subagent system prompt (~200 tokens)
          - Task objective (~100 tokens)
          - Parent's context slice (variable, curated by parent)
          - File contents (the actual code to work with)
          - Scope declaration (so the subagent knows its boundaries)
        """
        sections: list[str] = []

        # System framing
        sections.append(f"<system>\n{ContextIsolator.SUBAGENT_SYSTEM_PROMPT}</system>")

        # Task objective
        sections.append(f"<task>\n{task.objective}\n</task>")

        # Parent context (already curated — only the relevant slice)
        if task.context_slice.strip():
            sections.append(
                f"<parent_context>\n{task.context_slice}\n</parent_context>"
            )

        # File contents
        if task.file_contents:
            file_parts = []
            for path, content in task.file_contents.items():
                file_parts.append(f"### {path}\n```\n{content}\n```")
            sections.append(
                f"<files>\n" + "\n\n".join(file_parts) + "\n</files>"
            )

        # Scope declaration
        scope_desc = (
            f"Readable: {', '.join(task.scope.readable) or 'none'}\n"
            f"Writable: {', '.join(task.scope.writable) or 'none (read-only task)'}"
        )
        sections.append(f"<scope>\n{scope_desc}\n</scope>")

        context = "\n\n".join(sections)

        # Verify we're within budget
        tokens = estimate_tokens(context)
        if tokens > task.budget_tokens:
            context = ContextIsolator._trim_to_budget(context, task.budget_tokens)

        return context

    @staticmethod
    def _trim_to_budget(context: str, budget: int) -> str:
        """
        If the pre-loaded file contents push us over budget, truncate
        the largest files from the middle (keep head + tail).
        """
        # Rough approach: trim each file section proportionally
        # In production, you'd be smarter about which files to trim
        target_chars = int(budget * 3.5)  # reverse of estimate_tokens
        if len(context) <= target_chars:
            return context

        # Truncate by removing middle of the <files> section
        files_start = context.find("<files>")
        files_end = context.find("</files>")
        if files_start == -1 or files_end == -1:
            return context[:target_chars]

        before = context[:files_start]
        after = context[files_end:]
        available = target_chars - len(before) - len(after)

        files_section = context[files_start:files_end + len("</files>")]
        if available > 0 and available < len(files_section):
            half = available // 2
            files_section = (
                files_section[:half]
                + "\n\n... [truncated for budget] ...\n\n"
                + files_section[-half:]
            )

        return before + files_section + after


# ── subagent runner ──────────────────────────────────────────────────────

class SubagentRunner:
    """
    Runs a single subagent loop to completion.

    This is the inner agent loop — it takes the isolated context,
    runs tool calls, and produces a structured result. It's intentionally
    simpler than the parent agent loop: no compaction (budget is small
    enough), no memory persistence, no delegation.
    """

    def __init__(
        self,
        llm: Any,                   # LLM client (model-agnostic)
        tool_runner: Any,           # executes tool calls within scope
    ):
        self.llm = llm
        self.tool_runner = tool_runner

    async def run(self, task: SubagentTask) -> SubagentResult:
        """Execute a subagent task and return structured results."""
        start_time = time.monotonic()
        context = ContextIsolator.build_context(task)

        # The subagent's own conversation history (not shared with parent)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": context},
        ]

        file_changes: dict[str, str] = {}
        observations: list[str] = []
        turns = 0
        total_tokens = estimate_tokens(context)

        try:
            while turns < task.max_turns:
                turns += 1

                # Get LLM response
                response = await self.llm.agentic_complete(
                    messages=messages,
                    tools=self._scoped_tools(task.scope),
                    max_tokens=4096,
                )
                total_tokens += estimate_tokens(response.content)

                # Check for tool calls
                if response.tool_calls:
                    for tool_call in response.tool_calls:
                        # Enforce scope
                        if not self._check_scope(tool_call, task.scope):
                            observations.append(
                                f"BLOCKED: {tool_call.name} on {tool_call.args.get('path', '?')} "
                                f"— outside declared scope"
                            )
                            messages.append({
                                "role": "tool",
                                "content": f"Error: access denied — path outside your scope. "
                                           f"Writable: {task.scope.writable}",
                            })
                            continue

                        result = await self.tool_runner.execute(tool_call)
                        total_tokens += estimate_tokens(str(result))

                        messages.append({
                            "role": "assistant",
                            "content": response.content,
                        })
                        messages.append({
                            "role": "tool",
                            "content": str(result),
                        })

                        # Track file writes
                        if tool_call.name in ("write_file", "patch_file"):
                            path = tool_call.args.get("path", "")
                            file_changes[path] = result.get("new_content", "")

                    continue

                # No tool calls — agent is done (or stuck)
                # Parse structured output from the final message
                parsed = self._parse_final_response(response.content)
                file_changes.update(parsed.get("file_changes", {}))
                observations.extend(parsed.get("observations", []))

                return SubagentResult(
                    task_id=task.id,
                    status=SubagentStatus.COMPLETED,
                    summary=parsed.get("summary", response.content[:500]),
                    file_changes=file_changes,
                    observations=observations,
                    tokens_used=total_tokens,
                    turns_used=turns,
                    wall_time_seconds=time.monotonic() - start_time,
                )

            # Hit max turns — return what we have
            return SubagentResult(
                task_id=task.id,
                status=SubagentStatus.COMPLETED,
                summary=f"Completed after hitting {task.max_turns} turn limit.",
                file_changes=file_changes,
                observations=observations + ["Hit max turn limit — results may be incomplete."],
                tokens_used=total_tokens,
                turns_used=turns,
                wall_time_seconds=time.monotonic() - start_time,
            )

        except Exception as e:
            return SubagentResult(
                task_id=task.id,
                status=SubagentStatus.FAILED,
                summary=f"Failed with error: {e}",
                file_changes=file_changes,
                observations=observations,
                error=str(e),
                tokens_used=total_tokens,
                turns_used=turns,
                wall_time_seconds=time.monotonic() - start_time,
            )

    def _scoped_tools(self, scope: FileScope) -> list[dict]:
        """
        Return tool definitions filtered to the subagent's scope.

        Subagents get a reduced tool set:
          - read_file (within readable scope)
          - write_file / patch_file (within writable scope)
          - run_command (sandboxed)
          - search_text (within readable scope)

        They do NOT get:
          - spawn_subagent (no recursive delegation)
          - memory tools (only parent manages persistence)
          - git tools (parent handles commits)
        """
        tools = [
            {
                "name": "read_file",
                "description": "Read a file. Restricted to your readable scope.",
                "parameters": {"path": "string"},
            },
            {
                "name": "search_text",
                "description": "Search for text across files in your scope.",
                "parameters": {"query": "string", "path_glob": "string"},
            },
            {
                "name": "run_command",
                "description": "Run a shell command (sandboxed to workspace).",
                "parameters": {"command": "string"},
            },
        ]

        if scope.writable:
            tools.extend([
                {
                    "name": "write_file",
                    "description": "Write complete file contents. Must be in writable scope.",
                    "parameters": {"path": "string", "content": "string"},
                },
                {
                    "name": "patch_file",
                    "description": "Apply a targeted edit to a file. Must be in writable scope.",
                    "parameters": {
                        "path": "string",
                        "search": "string",
                        "replace": "string",
                    },
                },
            ])

        return tools

    def _check_scope(self, tool_call: Any, scope: FileScope) -> bool:
        """Verify a tool call is within the subagent's declared scope."""
        path = tool_call.args.get("path", "")
        if not path:
            return True  # commands without paths are allowed

        if tool_call.name in ("write_file", "patch_file"):
            return scope.can_write(path)
        elif tool_call.name in ("read_file", "search_text"):
            return scope.can_read(path)
        return True

    def _parse_final_response(self, content: str) -> dict:
        """
        Extract structured data from the subagent's final message.

        Subagents are prompted to output a structured format, but we
        handle free-text gracefully.
        """
        result: dict[str, Any] = {
            "summary": "",
            "file_changes": {},
            "observations": [],
        }

        # Try to find structured sections
        import re

        summary_match = re.search(
            r"(?:summary|what i did)[:\s]*(.+?)(?=\n(?:file|observation|$))",
            content, re.I | re.S,
        )
        if summary_match:
            result["summary"] = summary_match.group(1).strip()
        else:
            # Use first paragraph as summary
            paragraphs = content.strip().split("\n\n")
            result["summary"] = paragraphs[0] if paragraphs else content[:500]

        # Extract observations
        obs_matches = re.findall(
            r"(?:observation|note|warning)[:\s]*(.+?)(?=\n|$)",
            content, re.I,
        )
        result["observations"] = [m.strip() for m in obs_matches]

        return result


# ── orchestrator ─────────────────────────────────────────────────────────

class SubagentOrchestrator:
    """
    The parent-side coordinator that plans delegation, executes subagent
    waves, and merges results back into the parent context.

    This is the main interface the parent agent loop calls.
    """

    def __init__(
        self,
        llm: Any,
        tool_runner: Any,
        compactor: ContextCompactor,
        max_concurrent: int = 4,
    ):
        self.llm = llm
        self.tool_runner = tool_runner
        self.compactor = compactor
        self.max_concurrent = max_concurrent
        self.runner = SubagentRunner(llm, tool_runner)

        # Track all results for the session
        self.completed_results: list[SubagentResult] = []

    # ── planning ─────────────────────────────────────────────────────
    def plan_delegation(
        self,
        task_description: str,
        available_files: dict[str, str],
    ) -> DelegationPlan:
        """
        Ask the LLM to decompose a task into parallelizable subtasks.

        The parent agent calls this when it recognizes a task that
        benefits from decomposition (multi-file edits, independent
        analyses, etc.).

        Returns a DelegationPlan with tasks organized into waves.
        """
        # Build the planning prompt
        file_listing = "\n".join(
            f"  {path} ({estimate_tokens(content)} tokens)"
            for path, content in available_files.items()
        )

        planning_prompt = f"""Decompose this task into independent subtasks that can be executed by isolated subagents.

TASK: {task_description}

AVAILABLE FILES:
{file_listing}

Rules:
- Each subtask should be completable with minimal context (ideally 1-3 files).
- Group subtasks into waves. Tasks in the same wave run in parallel.
- Tasks in wave N+1 can depend on results from wave N.
- Each subtask needs: objective, list of files to read, list of files to write.
- Prefer fewer, larger subtasks over many tiny ones (subagent startup has overhead).
- If a task requires seeing the result of another task's edits, put it in a later wave.

Output format (one task per block):
WAVE 1:
TASK: <objective>
READ: <comma-separated file paths>
WRITE: <comma-separated file paths>
DEPENDS: <comma-separated task IDs, or "none">

WAVE 2:
...
"""
        # In production, this calls the LLM. Here we show the structure.
        # The LLM response is parsed into SubagentTask objects.
        #
        # For now, return an example structure showing the pattern:
        return self._parse_plan_response(
            planning_prompt, task_description, available_files
        )

    def _parse_plan_response(
        self,
        prompt: str,
        task_description: str,
        available_files: dict[str, str],
    ) -> DelegationPlan:
        """
        Parse the LLM's delegation plan into structured tasks.

        In a real implementation, this sends the prompt to the LLM and
        parses the response. Here we show the parsing logic.
        """
        import re

        # This would be: raw = await self.llm.complete(prompt)
        # For now, we show what the parser does with the LLM output.

        # Example: for a simple case, create a single-wave plan
        # with one task per writable file group.
        tasks: list[SubagentTask] = []
        paths = list(available_files.keys())

        # Heuristic grouping: files in the same directory go together
        groups: dict[str, list[str]] = {}
        for path in paths:
            import os
            dir_name = os.path.dirname(path) or "root"
            groups.setdefault(dir_name, []).append(path)

        parent_context = self.compactor.render()
        # Trim parent context to just the essentials for each subagent
        context_summary = self._extract_relevant_context(
            parent_context, task_description
        )

        for dir_name, group_paths in groups.items():
            file_contents = {p: available_files[p] for p in group_paths}
            task = SubagentTask(
                id=f"sub_{dir_name.replace('/', '_')}",
                objective=f"{task_description}\n\nFocus on files in: {dir_name}",
                context_slice=context_summary,
                file_contents=file_contents,
                scope=FileScope(
                    readable=group_paths + ["*.md", "*.toml"],
                    writable=group_paths,
                ),
            )
            tasks.append(task)

        return DelegationPlan(
            waves=[tasks],  # all independent → single wave
            rationale=f"Grouped {len(tasks)} tasks by directory for parallel execution.",
            estimated_total_tokens=sum(
                estimate_tokens(t.context_slice) +
                sum(estimate_tokens(c) for c in t.file_contents.values())
                for t in tasks
            ),
        )

    def _extract_relevant_context(
        self, full_context: str, task_description: str
    ) -> str:
        """
        Extract only the parts of the parent context relevant to a subtask.

        This is the critical isolation step. The full parent context
        might be 80k tokens. A subagent editing auth.py needs maybe
        the architecture decisions and the auth-related discussion —
        not the 30 turns about CSS styling.

        In production, this is an LLM call:
          "Given this task: {task}, extract the relevant context from: {full}"

        For the fallback, we do keyword overlap scoring.
        """
        task_words = set(task_description.lower().split())

        # Score each section of the parent context
        sections = full_context.split("\n\n")
        scored: list[tuple[float, str]] = []
        for section in sections:
            section_words = set(section.lower().split())
            overlap = len(task_words & section_words)
            if overlap > 0 or len(section) < 200:  # keep short sections
                scored.append((overlap, section))

        # Keep top sections within a budget
        scored.sort(key=lambda x: x[0], reverse=True)
        budget = 5000  # tokens for context slice
        kept: list[str] = []
        used = 0
        for score, section in scored:
            tokens = estimate_tokens(section)
            if used + tokens > budget:
                break
            kept.append(section)
            used += tokens

        return "\n\n".join(kept)

    # ── execution ────────────────────────────────────────────────────
    async def execute(self, plan: DelegationPlan) -> list[SubagentResult]:
        """
        Execute a delegation plan wave by wave.

        Within each wave, tasks run concurrently up to max_concurrent.
        Between waves, results from the previous wave are made available
        to the next wave's tasks (via dependency injection into their
        context slices).
        """
        all_results: list[SubagentResult] = []
        results_by_id: dict[str, SubagentResult] = {}

        for wave_idx, wave in enumerate(plan.waves):
            # Inject dependency results into tasks that need them
            for task in wave:
                if task.depends_on:
                    dep_context = self._build_dependency_context(
                        task.depends_on, results_by_id
                    )
                    task.context_slice += f"\n\n<dependency_results>\n{dep_context}\n</dependency_results>"

            # Execute wave with concurrency limit
            wave_results = await self._execute_wave(wave)

            for result in wave_results:
                results_by_id[result.task_id] = result
                all_results.append(result)

                # Push a summary into the parent's compactor
                self.compactor.push(
                    "system",
                    f"[Subagent {result.task_id}] {result.status.value}: {result.summary}",
                )

        self.completed_results.extend(all_results)
        return all_results

    async def _execute_wave(
        self, wave: list[SubagentTask]
    ) -> list[SubagentResult]:
        """Run all tasks in a wave concurrently, respecting max_concurrent."""
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def run_with_limit(task: SubagentTask) -> SubagentResult:
            async with semaphore:
                return await self.runner.run(task)

        # Sort by priority (higher first)
        wave.sort(key=lambda t: t.priority, reverse=True)

        results = await asyncio.gather(
            *[run_with_limit(task) for task in wave],
            return_exceptions=True,
        )

        # Convert exceptions to failed results
        processed: list[SubagentResult] = []
        for task, result in zip(wave, results):
            if isinstance(result, Exception):
                processed.append(SubagentResult(
                    task_id=task.id,
                    status=SubagentStatus.FAILED,
                    summary=f"Exception during execution: {result}",
                    file_changes={},
                    observations=[],
                    error=str(result),
                ))
            else:
                processed.append(result)

        return processed

    def _build_dependency_context(
        self,
        dep_ids: list[str],
        results: dict[str, SubagentResult],
    ) -> str:
        """
        Build a context snippet from dependency results for injection
        into a downstream task.
        """
        parts: list[str] = []
        for dep_id in dep_ids:
            result = results.get(dep_id)
            if not result:
                parts.append(f"[{dep_id}]: NOT COMPLETED (may still be running)")
                continue

            part = f"[{dep_id}] ({result.status.value}):\n{result.summary}"
            if result.observations:
                part += "\nObservations:\n" + "\n".join(
                    f"  - {obs}" for obs in result.observations
                )
            # Include file change summaries (not full contents — too large)
            if result.file_changes:
                part += f"\nModified files: {', '.join(result.file_changes.keys())}"

            parts.append(part)

        return "\n\n".join(parts)

    # ── result merging ───────────────────────────────────────────────
    def merge_results(
        self,
        results: list[SubagentResult],
    ) -> MergeReport:
        """
        Merge subagent results, detecting and flagging conflicts.

        Conflicts occur when two subagents modify the same file
        (shouldn't happen with proper scoping, but defensive coding).
        """
        merged_changes: dict[str, str] = {}
        conflicts: list[str] = []
        all_observations: list[str] = []

        for result in results:
            if result.status == SubagentStatus.FAILED:
                conflicts.append(
                    f"Task {result.task_id} failed: {result.error}"
                )
                continue

            for path, content in result.file_changes.items():
                if path in merged_changes:
                    conflicts.append(
                        f"CONFLICT: Both {result.task_id} and a previous task "
                        f"modified {path}. Keeping the later version."
                    )
                merged_changes[path] = content

            all_observations.extend(result.observations)

        return MergeReport(
            file_changes=merged_changes,
            conflicts=conflicts,
            observations=all_observations,
            success=len(conflicts) == 0,
        )


@dataclass
class MergeReport:
    """Summary of merged subagent results."""
    file_changes: dict[str, str]
    conflicts: list[str]
    observations: list[str]
    success: bool

    def summary(self) -> str:
        parts = [f"Modified {len(self.file_changes)} files."]
        if self.conflicts:
            parts.append(f"⚠ {len(self.conflicts)} conflicts detected.")
        if self.observations:
            parts.append(f"{len(self.observations)} observations from subagents.")
        return " ".join(parts)
```

## The Three Critical Design Decisions

**1. Subagents cannot spawn subagents.** This is a deliberate constraint. Recursive delegation creates exponential complexity — the parent loses track of what's happening, context budgets become impossible to manage, and error handling turns into a nightmare. Claude Code enforces a flat hierarchy: one orchestrator, N workers. If a subagent's task is too complex for its budget, it fails and the parent re-plans, possibly breaking the task down further itself.

**2. Context isolation is aggressive.** The subagent doesn't get the parent's conversation history. It gets a curated context slice — typically a short summary of relevant decisions and the specific files it needs. This is the key insight: most of what's in the parent's 100k token context is irrelevant to any individual subtask. The `_extract_relevant_context` method does keyword overlap as a fallback, but in production, the parent LLM itself selects what to pass down. This is why subagents can operate with 30-40k token budgets even when the parent is using 120k.

**3. Scope enforcement is at the tool level, not trust-based.** The subagent's system prompt says "only modify files in your scope," but the `SubagentRunner._check_scope` method actually enforces it. If a subagent tries to write outside its declared writable paths, the tool call is blocked and the subagent gets an error message. This makes parallel execution safe — two subagents running concurrently cannot step on each other's files because their writable scopes are disjoint by construction.

## Wave-Based Parallelism

The wave model is simpler and more predictable than a full dependency DAG:

```
Wave 1 (parallel):
  ├── Edit src/auth.py       (write scope: src/auth.py)
  ├── Edit src/db.py         (write scope: src/db.py)
  └── Edit src/api.py        (write scope: src/api.py)

Wave 2 (parallel, depends on wave 1):
  ├── Write tests for auth   (read: src/auth.py, write: tests/test_auth.py)
  └── Write tests for db     (read: src/db.py, write: tests/test_db.py)

Wave 3 (sequential):
  └── Integration test        (read: everything, write: tests/test_integration.py)
```

Wave 2 tasks get dependency context injected — they see the summaries and file change lists from wave 1, so they know what was actually modified. They don't see wave 1's raw conversation, just the structured `SubagentResult`.

The `max_concurrent` semaphore prevents resource exhaustion. Running 4 subagents in parallel means 4 concurrent LLM calls and 4× the token throughput. On most API rate limits, 3-4 concurrent is the sweet spot.

## When to Delegate vs. Do It Inline

Not every task should be delegated. The parent agent needs heuristics for when delegation is worth the overhead:

Delegation wins when the task involves editing 3+ files with independent concerns, when the combined file contents exceed ~40% of the parent's remaining context budget, or when subtasks have clear boundaries with no cross-file dependencies within a wave.

Delegation loses when the task requires tight coordination between files (e.g., renaming a function that's imported everywhere), when the overhead of spawning and merging exceeds the time saved, or when there's only one file to edit. In Claude Code's behavior, you'll notice it tends to handle single-file edits inline and only delegates when it recognizes a multi-file, decomposable task.
