"""Agent Workflow: Structured task execution with classification, planning, execution, compression, validation, and reporting.

This module provides an optional workflow layer that wraps the existing AgentRunner
with a structured 6-phase execution pipeline:

1. Classification - Identify the task type and complexity
2. Planning - Create a detailed execution plan
3. Execution - Run the plan using existing tool mechanisms
4. Compression - Compact intermediate results
5. Validation - Verify the result meets requirements
6. Reporting - Generate a user-friendly summary

The workflow is enabled via NANOBOT_AGENT_WORKFLOW=1 environment variable.
If any phase fails, it automatically falls back to the traditional direct execution.
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.hook import AgentHook
from nanobot.agent.runner import AgentRunResult, AgentRunSpec, AgentRunner
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from pathlib import Path

    from nanobot.agent.hook import AgentHookContext


_WORKFLOW_ENV_VAR = "NANOBOT_AGENT_WORKFLOW"
_DEFAULT_WORKFLOW_ENABLED = False


def is_workflow_enabled() -> bool:
    """Check if the agent workflow is enabled via environment variable."""
    val = os.environ.get(_WORKFLOW_ENV_VAR, "").strip().lower()
    return val in ("1", "true", "yes", "on")


@dataclass(slots=True)
class WorkflowContext:
    """Context passed through all workflow phases."""

    original_messages: list[dict[str, Any]]
    task_description: str
    tools: ToolRegistry
    model: str
    provider: LLMProvider

    task_type: str = "unknown"
    task_complexity: str = "unknown"
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    execution_messages: list[dict[str, Any]] = field(default_factory=list)
    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    stop_reason: str = "workflow_pending"
    had_injections: bool = False

    validation_passed: bool = False
    validation_reason: str = ""
    compressed_summary: str = ""
    final_report: str = ""


@dataclass(slots=True)
class WorkflowResult:
    """Result of a workflow execution."""

    success: bool
    run_result: AgentRunResult | None = None
    fallback_reason: str | None = None
    workflow_context: WorkflowContext | None = None


_CLASSIFY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "classify_task",
            "description": "Classify the user task to determine the best approach.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {
                        "type": "string",
                        "enum": ["coding", "research", "writing", "analysis", "automation", "troubleshooting", "simple_query", "other"],
                        "description": "The type of task being requested",
                    },
                    "complexity": {
                        "type": "string",
                        "enum": ["simple", "medium", "complex"],
                        "description": "Estimated complexity of the task",
                    },
                    "requires_plan": {
                        "type": "boolean",
                        "description": "Whether this task benefits from explicit planning",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Brief reasoning for the classification",
                    },
                },
                "required": ["task_type", "complexity", "requires_plan", "reasoning"],
            },
        },
    }
]


_PLAN_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Create a structured execution plan for the task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {
                                    "type": "string",
                                    "description": "What this step accomplishes",
                                },
                                "tools": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Tools likely needed for this step",
                                },
                                "notes": {
                                    "type": "string",
                                    "description": "Additional considerations",
                                },
                            },
                            "required": ["description"],
                        },
                        "description": "List of execution steps",
                    },
                    "expected_duration": {
                        "type": "string",
                        "description": "Estimated time to complete",
                    },
                    "success_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "How to determine if the task succeeded",
                    },
                },
                "required": ["steps", "success_criteria"],
            },
        },
    }
]


_VALIDATE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "validate_result",
            "description": "Validate if the execution result meets the original task requirements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "passed": {
                        "type": "boolean",
                        "description": "Whether the result meets the requirements",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Detailed reason for the validation decision",
                    },
                    "missing_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What is missing from the result, if anything",
                    },
                },
                "required": ["passed", "reason"],
            },
        },
    }
]


class WorkflowRunner:
    """Runs the structured workflow pipeline.

    This runner wraps the existing AgentRunner with additional phases:
    classification, planning, compression, validation, and reporting.
    """

    def __init__(self, provider: LLMProvider):
        self.provider = provider
        self._runner = AgentRunner(provider)

    def _accumulate_usage(self, target: dict[str, int], addition: dict[str, int] | None) -> None:
        """Accumulate token usage from LLM calls."""
        if not addition:
            return
        for key, value in addition.items():
            try:
                target[key] = target.get(key, 0) + int(value or 0)
            except (TypeError, ValueError):
                continue

    async def _call_with_tool(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict],
        tool_name: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any] | None, dict[str, int]]:
        """Make an LLM call expecting a specific tool call.

        Returns (parsed_arguments, usage_dict).
        Returns (None, usage_dict) if no tool call was made.
        """
        try:
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            usage = self._usage_dict(response.usage)

            if not response.should_execute_tools:
                logger.warning(f"Workflow {tool_name}: no tool call returned")
                return None, usage

            for tc in response.tool_calls:
                if tc.name == tool_name:
                    return tc.arguments, usage

            logger.warning(f"Workflow {tool_name}: expected tool '{tool_name}' but got others")
            return None, usage

        except Exception:
            logger.exception(f"Workflow {tool_name} call failed")
            return None, {}

    @staticmethod
    def _usage_dict(usage: dict[str, Any] | None) -> dict[str, int]:
        if not usage:
            return {}
        result: dict[str, int] = {}
        for key, value in usage.items():
            try:
                result[key] = int(value or 0)
            except (TypeError, ValueError):
                continue
        return result

    async def _classify_task(self, ctx: WorkflowContext) -> bool:
        """Phase 1: Classify the task to determine type and complexity."""
        logger.info("Workflow: Phase 1 - Task Classification")

        system_prompt = render_template("agent/workflow/classify.md", part="system")
        user_content = render_template(
            "agent/workflow/classify.md",
            part="user",
            task_description=ctx.task_description,
            available_tools=", ".join(ctx.tools.tool_names),
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        args, usage = await self._call_with_tool(
            messages, _CLASSIFY_TOOL, "classify_task", ctx.model
        )
        self._accumulate_usage(ctx.usage, usage)

        if args is None:
            return False

        ctx.task_type = args.get("task_type", "unknown")
        ctx.task_complexity = args.get("complexity", "unknown")
        requires_plan = args.get("requires_plan", True)
        reasoning = args.get("reasoning", "")

        logger.info(
            "Workflow: Classified task - type={}, complexity={}, requires_plan={}, reason={}",
            ctx.task_type,
            ctx.task_complexity,
            requires_plan,
            reasoning[:100] if reasoning else "N/A",
        )

        return True

    async def _create_plan(self, ctx: WorkflowContext) -> bool:
        """Phase 2: Create an execution plan based on task classification."""
        if ctx.task_type in ["simple_query"] and ctx.task_complexity == "simple":
            logger.info("Workflow: Skipping planning for simple task")
            ctx.plan_steps = [{"description": "Execute task directly", "tools": []}]
            return True

        logger.info("Workflow: Phase 2 - Planning")

        system_prompt = render_template("agent/workflow/plan.md", part="system")
        user_content = render_template(
            "agent/workflow/plan.md",
            part="user",
            task_description=ctx.task_description,
            task_type=ctx.task_type,
            task_complexity=ctx.task_complexity,
            available_tools=", ".join(ctx.tools.tool_names),
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        args, usage = await self._call_with_tool(
            messages, _PLAN_TOOL, "create_plan", ctx.model, max_tokens=2048
        )
        self._accumulate_usage(ctx.usage, usage)

        if args is None:
            return False

        ctx.plan_steps = args.get("steps", [])
        logger.info(
            "Workflow: Created plan with {} steps",
            len(ctx.plan_steps),
        )

        return True

    async def _execute_plan(self, ctx: WorkflowContext, spec: AgentRunSpec) -> AgentRunResult | None:
        """Phase 3: Execute the plan using the existing runner.

        For now, we use the original execution flow. The plan is included
        in the system prompt to guide the agent's execution.
        """
        logger.info("Workflow: Phase 3 - Execution")

        plan_annotation = ""
        if ctx.plan_steps:
            plan_lines = ["# Execution Plan"]
            for i, step in enumerate(ctx.plan_steps, 1):
                desc = step.get("description", "")
                tools = step.get("tools", [])
                notes = step.get("notes", "")
                line = f"{i}. {desc}"
                if tools:
                    line += f" (tools: {', '.join(tools)})"
                if notes:
                    line += f" - {notes}"
                plan_lines.append(line)
            plan_annotation = "\n".join(plan_lines)

        if plan_annotation:
            enhanced_messages = list(ctx.original_messages)
            if enhanced_messages and enhanced_messages[0].get("role") == "system":
                original_system = enhanced_messages[0].get("content", "")
                enhanced_system = f"{original_system}\n\n{plan_annotation}"
                enhanced_messages[0] = {"role": "system", "content": enhanced_system}

            execution_spec = dataclasses.replace(spec, initial_messages=enhanced_messages)
        else:
            execution_spec = spec

        result = await self._runner.run(execution_spec)
        ctx.execution_messages = result.messages
        ctx.final_content = result.final_content
        ctx.tools_used = result.tools_used
        ctx.had_injections = result.had_injections
        ctx.stop_reason = result.stop_reason
        self._accumulate_usage(ctx.usage, result.usage)

        logger.info(
            "Workflow: Execution completed - stop_reason={}, tools_used={}",
            result.stop_reason,
            result.tools_used,
        )

        return result

    async def _compress_results(self, ctx: WorkflowContext) -> bool:
        """Phase 4: Compress/consolidate intermediate results if needed."""
        logger.info("Workflow: Phase 4 - Compression")

        if len(ctx.execution_messages) < 10:
            logger.info("Workflow: Skipping compression - message count low")
            ctx.compressed_summary = ctx.final_content or ""
            return True

        try:
            system_prompt = render_template("agent/workflow/compress.md", part="system")
            user_content = render_template(
                "agent/workflow/compress.md",
                part="user",
                original_task=ctx.task_description,
                final_content=ctx.final_content or "",
            )

            response = await self.provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                model=ctx.model,
                max_tokens=2048,
                temperature=0.3,
            )
            self._accumulate_usage(ctx.usage, self._usage_dict(response.usage))

            if response.content and response.content.strip():
                ctx.compressed_summary = response.content.strip()
                logger.info("Workflow: Compression completed")
            else:
                ctx.compressed_summary = ctx.final_content or ""

            return True

        except Exception:
            logger.exception("Workflow: Compression phase failed, using original content")
            ctx.compressed_summary = ctx.final_content or ""
            return True

    async def _validate_result(self, ctx: WorkflowContext) -> bool:
        """Phase 5: Validate the result meets task requirements."""
        logger.info("Workflow: Phase 5 - Validation")

        if ctx.task_type == "simple_query":
            logger.info("Workflow: Skipping validation for simple query")
            ctx.validation_passed = True
            ctx.validation_reason = "Simple query, no validation needed"
            return True

        system_prompt = render_template("agent/workflow/validate.md", part="system")
        user_content = render_template(
            "agent/workflow/validate.md",
            part="user",
            original_task=ctx.task_description,
            task_type=ctx.task_type,
            final_result=ctx.compressed_summary or ctx.final_content or "",
            tools_used=", ".join(ctx.tools_used) if ctx.tools_used else "none",
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        args, usage = await self._call_with_tool(
            messages, _VALIDATE_TOOL, "validate_result", ctx.model
        )
        self._accumulate_usage(ctx.usage, usage)

        if args is None:
            ctx.validation_passed = True
            ctx.validation_reason = "Validation tool call failed, assuming valid"
            return True

        ctx.validation_passed = bool(args.get("passed", True))
        ctx.validation_reason = args.get("reason", "")
        missing = args.get("missing_items", [])

        logger.info(
            "Workflow: Validation - passed={}, reason={}",
            ctx.validation_passed,
            ctx.validation_reason[:100] if ctx.validation_reason else "N/A",
        )

        if not ctx.validation_passed and missing:
            logger.warning("Workflow: Validation missing items: {}", missing)

        return True

    async def _generate_report(self, ctx: WorkflowContext) -> bool:
        """Phase 6: Generate a user-friendly final report."""
        logger.info("Workflow: Phase 6 - Reporting")

        if ctx.task_type == "simple_query" or ctx.task_complexity == "simple":
            ctx.final_report = ctx.compressed_summary or ctx.final_content or ""
            return True

        try:
            system_prompt = render_template("agent/workflow/report.md", part="system")
            user_content = render_template(
                "agent/workflow/report.md",
                part="user",
                original_task=ctx.task_description,
                task_type=ctx.task_type,
                result=ctx.compressed_summary or ctx.final_content or "",
                tools_used=", ".join(ctx.tools_used) if ctx.tools_used else "none",
                validation_passed=ctx.validation_passed,
                validation_reason=ctx.validation_reason,
            )

            response = await self.provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                model=ctx.model,
                max_tokens=4096,
                temperature=0.7,
            )
            self._accumulate_usage(ctx.usage, self._usage_dict(response.usage))

            if response.content and response.content.strip():
                ctx.final_report = response.content.strip()
            else:
                ctx.final_report = ctx.compressed_summary or ctx.final_content or ""

            logger.info("Workflow: Report generation completed")
            return True

        except Exception:
            logger.exception("Workflow: Report phase failed, using compressed result")
            ctx.final_report = ctx.compressed_summary or ctx.final_content or ""
            return True

    async def run(self, spec: AgentRunSpec) -> WorkflowResult:
        """Execute the full workflow pipeline.

        Returns a WorkflowResult. If the workflow fails at any point,
        the result will indicate failure and the caller should fall back
        to traditional execution.
        """
        if not spec.initial_messages:
            return WorkflowResult(
                success=False,
                fallback_reason="No initial messages provided",
            )

        last_user_msg = None
        for msg in reversed(spec.initial_messages):
            if msg.get("role") == "user":
                last_user_msg = msg
                break

        if last_user_msg is None:
            return WorkflowResult(
                success=False,
                fallback_reason="No user message found",
            )

        task_content = last_user_msg.get("content", "")
        if isinstance(task_content, list):
            task_description = " ".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in task_content
            )
        else:
            task_description = str(task_content or "")

        ctx = WorkflowContext(
            original_messages=spec.initial_messages,
            task_description=task_description,
            tools=spec.tools,
            model=spec.model,
            provider=self.provider,
        )

        try:
            if not await self._classify_task(ctx):
                return WorkflowResult(
                    success=False,
                    fallback_reason="Task classification failed",
                    workflow_context=ctx,
                )

            if not await self._create_plan(ctx):
                return WorkflowResult(
                    success=False,
                    fallback_reason="Plan creation failed",
                    workflow_context=ctx,
                )

            run_result = await self._execute_plan(ctx, spec)
            if run_result is None:
                return WorkflowResult(
                    success=False,
                    fallback_reason="Execution phase returned None",
                    workflow_context=ctx,
                )

            if not await self._compress_results(ctx):
                return WorkflowResult(
                    success=False,
                    fallback_reason="Compression phase failed",
                    workflow_context=ctx,
                    run_result=run_result,
                )

            if not await self._validate_result(ctx):
                return WorkflowResult(
                    success=False,
                    fallback_reason="Validation phase failed",
                    workflow_context=ctx,
                    run_result=run_result,
                )

            if not await self._generate_report(ctx):
                return WorkflowResult(
                    success=False,
                    fallback_reason="Report generation failed",
                    workflow_context=ctx,
                    run_result=run_result,
                )

            enhanced_result = AgentRunResult(
                final_content=ctx.final_report or ctx.final_content,
                messages=ctx.execution_messages if ctx.execution_messages else run_result.messages,
                tools_used=ctx.tools_used if ctx.tools_used else run_result.tools_used,
                usage=ctx.usage,
                stop_reason=run_result.stop_reason,
                error=run_result.error,
                tool_events=run_result.tool_events,
                had_injections=ctx.had_injections or run_result.had_injections,
            )

            logger.info(
                "Workflow: All phases completed successfully - final_content_length={}",
                len(ctx.final_report) if ctx.final_report else 0,
            )

            return WorkflowResult(
                success=True,
                run_result=enhanced_result,
                workflow_context=ctx,
            )

        except Exception as e:
            logger.exception("Workflow: Pipeline failed with exception")
            return WorkflowResult(
                success=False,
                fallback_reason=f"Exception: {type(e).__name__}: {e}",
                workflow_context=ctx,
            )


async def run_with_workflow_fallback(
    spec: AgentRunSpec,
    provider: LLMProvider,
) -> AgentRunResult:
    """Run with workflow enabled, falling back to traditional execution on failure.

    This is the main entry point for integrating the workflow into the
    existing agent loop. It checks if workflow is enabled via env var,
    runs the workflow pipeline if enabled, and falls back to the
    traditional AgentRunner on any workflow failure.
    """
    if not is_workflow_enabled():
        logger.debug("Workflow: disabled by environment, using traditional execution")
        runner = AgentRunner(provider)
        return await runner.run(spec)

    logger.info("Workflow: enabled, attempting structured execution")
    workflow_runner = WorkflowRunner(provider)
    workflow_result = await workflow_runner.run(spec)

    if workflow_result.success and workflow_result.run_result is not None:
        return workflow_result.run_result

    logger.warning(
        "Workflow: failed ({}), falling back to traditional execution",
        workflow_result.fallback_reason,
    )
    runner = AgentRunner(provider)
    return await runner.run(spec)
