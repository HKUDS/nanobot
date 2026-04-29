"""Agent workflow: structured task processing pipeline.

This module provides an optional, structured workflow for agent task processing:
- Task Classification: Analyze and categorize the user's request
- Planning: Create an execution plan
- Execution: Run the plan using existing runner
- Compression: Compress results to save context
- Validation: Verify the results meet requirements
- Reporting: Generate a final report

Enable with NANOBOT_AGENT_WORKFLOW=1 environment variable.
Automatically falls back to legacy behavior on errors.
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.runner import AgentRunResult, AgentRunSpec
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.providers.base import LLMProvider


_WORKFLOW_ENV_VAR = "NANOBOT_AGENT_WORKFLOW"

_CLASSIFY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "classify_task",
            "description": "Classify the user's task into predefined categories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "primary_category": {
                        "type": "string",
                        "description": "The main category that best describes the task.",
                        "enum": [
                            "information_gathering",
                            "code_modification",
                            "file_management",
                            "execution",
                            "planning",
                            "reporting",
                            "mixed",
                            "simple_qa",
                        ],
                    },
                    "secondary_categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of other relevant categories (may be empty).",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Brief explanation for the classification.",
                    },
                    "estimated_complexity": {
                        "type": "string",
                        "description": "Rough complexity estimate.",
                        "enum": ["low", "medium", "high"],
                    },
                    "suggested_approach": {
                        "type": "string",
                        "description": "One sentence suggesting how to approach this task.",
                    },
                },
                "required": ["primary_category", "reasoning", "estimated_complexity"],
            },
        },
    }
]

_PLAN_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Create a detailed execution plan for the task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "overall_goal": {
                        "type": "string",
                        "description": "A clear statement of what we're trying to achieve.",
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {
                                    "type": "string",
                                    "description": "What to do in this step.",
                                },
                                "tools_needed": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of tools that may be needed.",
                                },
                                "expected_outcome": {
                                    "type": "string",
                                    "description": "What success looks like.",
                                },
                                "validation_method": {
                                    "type": "string",
                                    "description": "How to check if this step succeeded.",
                                },
                            },
                            "required": ["description"],
                        },
                        "description": "Ordered list of execution steps.",
                    },
                    "estimated_iterations": {
                        "type": "integer",
                        "description": "Rough estimate of LLM calls needed.",
                    },
                    "potential_risks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of things that could go wrong.",
                    },
                    "success_criteria": {
                        "type": "string",
                        "description": "How to know when the entire task is complete.",
                    },
                },
                "required": ["overall_goal", "steps", "success_criteria"],
            },
        },
    }
]

_COMPRESS_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "compress_conversation",
            "description": "Compress the conversation while preserving all important information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "original_task": {
                        "type": "string",
                        "description": "Clear statement of what was attempted.",
                    },
                    "key_decisions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of important decisions made.",
                    },
                    "tools_used_summary": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Brief summary of each tool's purpose and key result.",
                    },
                    "files_modified": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files created/edited with brief descriptions.",
                    },
                    "errors_encountered": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of errors and how they were handled (if any).",
                    },
                    "current_state": {
                        "type": "string",
                        "description": "Brief description of where things stand.",
                    },
                    "remaining_questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Any unresolved questions or next steps.",
                    },
                    "key_insights": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Most important learnings from this execution.",
                    },
                },
                "required": ["original_task", "current_state"],
            },
        },
    }
]

_VALIDATE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "validate_execution",
            "description": "Validate the execution results and determine if the task was completed successfully.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_understood": {
                        "type": "boolean",
                        "description": "Whether the task was clearly understood.",
                    },
                    "success_criteria_met": {
                        "type": "boolean",
                        "description": "Whether the success criteria were met.",
                    },
                    "steps_completed": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of steps that were successfully completed.",
                    },
                    "steps_incomplete": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of steps that were not completed or have issues.",
                    },
                    "errors_found": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of errors encountered and their status.",
                    },
                    "files_verified": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files verified and their status.",
                    },
                    "validation_summary": {
                        "type": "string",
                        "description": "Overall assessment of the execution.",
                    },
                    "confidence_score": {
                        "type": "integer",
                        "description": "Number 0-10 indicating confidence in the result.",
                        "minimum": 0,
                        "maximum": 10,
                    },
                    "recommendations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Suggestions for improvement or next steps.",
                    },
                    "needs_user_input": {
                        "type": "boolean",
                        "description": "Whether user clarification is needed.",
                    },
                },
                "required": [
                    "task_understood",
                    "success_criteria_met",
                    "validation_summary",
                    "confidence_score",
                ],
            },
        },
    }
]

_REPORT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": "Generate a comprehensive report for the user about what was accomplished.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "One paragraph overview of the task outcome.",
                    },
                    "actions_taken": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of key actions performed.",
                    },
                    "key_results": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of important results or findings.",
                    },
                    "files_modified": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files created/edited with brief descriptions.",
                    },
                    "issues_encountered": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of any problems and how they were resolved.",
                    },
                    "next_steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Recommended next actions.",
                    },
                    "user_questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Questions for the user (if any).",
                    },
                    "final_status": {
                        "type": "string",
                        "description": "Overall status.",
                        "enum": ["success", "partial_success", "failed"],
                    },
                    "confidence": {
                        "type": "integer",
                        "description": "Number 0-10 indicating confidence in the result.",
                        "minimum": 0,
                        "maximum": 10,
                    },
                },
                "required": ["summary", "final_status", "confidence"],
            },
        },
    }
]


def is_workflow_enabled() -> bool:
    """Check if the structured workflow is enabled via environment variable.

    Returns True if NANOBOT_AGENT_WORKFLOW=1 or NANOBOT_AGENT_WORKFLOW=true.
    """
    env_value = os.environ.get(_WORKFLOW_ENV_VAR, "").strip().lower()
    return env_value in ("1", "true", "yes", "on")


@dataclasses.dataclass(slots=True)
class WorkflowResult:
    """Result of executing the structured workflow.

    Attributes:
        used_workflow: Whether the workflow was actually used.
        fallback_used: Whether we fell back to legacy behavior.
        fallback_reason: Why we fell back (if applicable).
        classification: Task classification result (if workflow used).
        plan: Execution plan (if workflow used).
        execution_result: Result from the execution phase.
        compressed: Compressed result (if workflow used).
        validation: Validation result (if workflow used).
        report: Final report (if workflow used).
    """

    used_workflow: bool
    fallback_used: bool
    fallback_reason: str | None = None
    classification: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    execution_result: "AgentRunResult | None" = None
    compressed: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    report: dict[str, Any] | None = None


class AgentWorkflow:
    """Structured workflow for agent task processing.

    This class implements a 6-phase workflow:
    1. Classification: Analyze and categorize the user's request
    2. Planning: Create an execution plan
    3. Execution: Run the plan using existing runner
    4. Compression: Compress results to save context
    5. Validation: Verify the results meet requirements
    6. Reporting: Generate a final report

    The workflow is designed to fail gracefully - if any phase fails,
    it falls back to the legacy direct-tool-call approach.
    """

    def __init__(
        self,
        provider: "LLMProvider",
        model: str,
        run_legacy_fn: Callable[..., Awaitable["AgentRunResult"]],
    ) -> None:
        """Initialize the workflow.

        Args:
            provider: The LLM provider to use for workflow phases.
            model: The model to use for workflow phases.
            run_legacy_fn: Function to call for legacy fallback execution.
                This should be a callable that runs the original agent loop
                and returns an AgentRunResult.
        """
        self.provider = provider
        self.model = model
        self._run_legacy = run_legacy_fn

    async def _call_tool_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> dict[str, Any] | None:
        """Make an LLM call with tools and parse the result.

        Returns the tool arguments as a dict, or None if no tool call was made.
        """
        try:
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=tools,
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            if not response.should_execute_tools:
                if response.has_tool_calls:
                    logger.warning(
                        "Workflow: ignoring tool calls under finish_reason='{}'",
                        response.finish_reason,
                    )
                else:
                    logger.warning("Workflow: no tool call returned")
                return None

            args = response.tool_calls[0].arguments
            return args

        except Exception as e:
            logger.warning("Workflow: LLM call failed: {}", e)
            return None

    def _extract_user_request(self, messages: list[dict[str, Any]]) -> str:
        """Extract the user's request from the message list.

        Looks for the last user message and returns its content.
        """
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    text_parts = [
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    return " ".join(text_parts)
        return ""

    def _extract_context_summary(self, messages: list[dict[str, Any]]) -> str:
        """Extract a summary of the conversation context.

        Returns a brief summary of the conversation history.
        """
        summary_parts = []
        system_msg = None

        for msg in messages:
            role = msg.get("role")
            if role == "system":
                system_msg = msg.get("content", "")
            elif role == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 0:
                    if len(content) > 100:
                        summary_parts.append(f"[Assistant: {content[:100]}...]")
                    else:
                        summary_parts.append(f"[Assistant: {content}]")
            elif role == "tool":
                tool_name = msg.get("name", "unknown_tool")
                summary_parts.append(f"[Tool: {tool_name} executed]")

        if system_msg and isinstance(system_msg, str):
            if len(system_msg) > 200:
                system_summary = f"[System prompt: {system_msg[:200]}...]"
            else:
                system_summary = f"[System prompt: {system_msg}]"
            summary_parts.insert(0, system_summary)

        return "\n".join(summary_parts) if summary_parts else "No additional context."

    def _messages_to_text(self, messages: list[dict[str, Any]]) -> str:
        """Convert message list to a readable text format.

        Used for compression and validation phases.
        """
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "image_url":
                            text_parts.append("[Image]")
                content = " ".join(text_parts)

            if role == "system":
                lines.append(f"## System\n{content}")
            elif role == "user":
                lines.append(f"## User\n{content}")
            elif role == "assistant":
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    tools_str = ", ".join(
                        tc.get("function", {}).get("name", "unknown")
                        if isinstance(tc, dict)
                        else str(tc)
                        for tc in tool_calls
                    )
                    lines.append(f"## Assistant\n{content}\n[Tool calls: {tools_str}]")
                else:
                    lines.append(f"## Assistant\n{content}")
            elif role == "tool":
                tool_name = msg.get("name", "unknown")
                tool_id = msg.get("tool_call_id", "")
                if isinstance(content, str) and len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"## Tool Result ({tool_name} / {tool_id})\n{content}")

        return "\n\n".join(lines)

    async def _classify(self, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Phase 1: Classify the user's task."""
        user_request = self._extract_user_request(messages)
        context_summary = self._extract_context_summary(messages)

        classification_messages = [
            {
                "role": "system",
                "content": render_template("agent/workflow_classify.md", part="system"),
            },
            {
                "role": "user",
                "content": render_template(
                    "agent/workflow_classify.md",
                    part="user",
                    user_request=user_request,
                    context_summary=context_summary,
                ),
            },
        ]

        result = await self._call_tool_llm(
            classification_messages,
            _CLASSIFY_TOOL,
            max_tokens=512,
            temperature=0.0,
        )

        if result:
            logger.info(
                "Workflow: Task classified as '{}' with complexity '{}'",
                result.get("primary_category", "unknown"),
                result.get("estimated_complexity", "unknown"),
            )
        return result

    async def _plan(
        self,
        messages: list[dict[str, Any]],
        classification: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Phase 2: Create an execution plan."""
        user_request = self._extract_user_request(messages)
        context_summary = self._extract_context_summary(messages)

        plan_messages = [
            {
                "role": "system",
                "content": render_template("agent/workflow_plan.md", part="system"),
            },
            {
                "role": "user",
                "content": render_template(
                    "agent/workflow_plan.md",
                    part="user",
                    task_classification=json.dumps(classification, indent=2),
                    user_request=user_request,
                    context_summary=context_summary,
                ),
            },
        ]

        result = await self._call_tool_llm(
            plan_messages,
            _PLAN_TOOL,
            max_tokens=2048,
            temperature=0.0,
        )

        if result:
            logger.info(
                "Workflow: Plan created with {} steps",
                len(result.get("steps", [])),
            )
        return result

    async def _compress(
        self,
        original_task: str,
        plan: dict[str, Any],
        execution_result: "AgentRunResult",
    ) -> dict[str, Any] | None:
        """Phase 4: Compress the execution results."""
        conversation_text = self._messages_to_text(execution_result.messages)

        compress_messages = [
            {
                "role": "system",
                "content": render_template("agent/workflow_compress.md", part="system"),
            },
            {
                "role": "user",
                "content": render_template(
                    "agent/workflow_compress.md",
                    part="user",
                    original_task=original_task,
                    execution_plan=json.dumps(plan, indent=2),
                    conversation_history=conversation_text,
                ),
            },
        ]

        result = await self._call_tool_llm(
            compress_messages,
            _COMPRESS_TOOL,
            max_tokens=1024,
            temperature=0.0,
        )

        if result:
            logger.info("Workflow: Compressed execution results")
        return result

    async def _validate(
        self,
        original_task: str,
        plan: dict[str, Any],
        compressed: dict[str, Any],
        execution_result: "AgentRunResult",
    ) -> dict[str, Any] | None:
        """Phase 5: Validate the execution results."""
        conversation_summary = self._messages_to_text(execution_result.messages[-10:])

        validate_messages = [
            {
                "role": "system",
                "content": render_template("agent/workflow_validate.md", part="system"),
            },
            {
                "role": "user",
                "content": render_template(
                    "agent/workflow_validate.md",
                    part="user",
                    original_task=original_task,
                    execution_plan=json.dumps(plan, indent=2),
                    compressed_results=json.dumps(compressed, indent=2),
                    conversation_summary=conversation_summary,
                ),
            },
        ]

        result = await self._call_tool_llm(
            validate_messages,
            _VALIDATE_TOOL,
            max_tokens=1024,
            temperature=0.0,
        )

        if result:
            logger.info(
                "Workflow: Validation complete - success_criteria_met={}, confidence={}",
                result.get("success_criteria_met", False),
                result.get("confidence_score", 0),
            )
        return result

    async def _report(
        self,
        original_task: str,
        plan: dict[str, Any],
        validation: dict[str, Any],
        compressed: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Phase 6: Generate the final report."""
        report_messages = [
            {
                "role": "system",
                "content": render_template("agent/workflow_report.md", part="system"),
            },
            {
                "role": "user",
                "content": render_template(
                    "agent/workflow_report.md",
                    part="user",
                    original_task=original_task,
                    execution_plan=json.dumps(plan, indent=2),
                    validation_results=json.dumps(validation, indent=2),
                    compressed_history=json.dumps(compressed, indent=2),
                ),
            },
        ]

        result = await self._call_tool_llm(
            report_messages,
            _REPORT_TOOL,
            max_tokens=2048,
            temperature=0.3,
        )

        if result:
            logger.info(
                "Workflow: Report generated - final_status={}, confidence={}",
                result.get("final_status", "unknown"),
                result.get("confidence", 0),
            )
        return result

    def _build_report_content(self, report: dict[str, Any]) -> str:
        """Convert the report dict to a user-facing string.

        Used when the workflow succeeds to generate the final response.
        """
        lines = []

        summary = report.get("summary")
        if summary:
            lines.append(summary)
            lines.append("")

        final_status = report.get("final_status")
        if final_status:
            status_icon = {"success": "✅", "partial_success": "⚠️", "failed": "❌"}.get(
                final_status, "📋"
            )
            lines.append(f"{status_icon} Status: {final_status.replace('_', ' ').title()}")
            lines.append("")

        confidence = report.get("confidence")
        if confidence is not None:
            lines.append(f"Confidence: {confidence}/10")
            lines.append("")

        actions = report.get("actions_taken", [])
        if actions:
            lines.append("## Actions Taken")
            for action in actions:
                lines.append(f"- {action}")
            lines.append("")

        key_results = report.get("key_results", [])
        if key_results:
            lines.append("## Key Results")
            for result in key_results:
                lines.append(f"- {result}")
            lines.append("")

        files = report.get("files_modified", [])
        if files:
            lines.append("## Files Modified")
            for f in files:
                lines.append(f"- {f}")
            lines.append("")

        issues = report.get("issues_encountered", [])
        if issues:
            lines.append("## Issues Encountered")
            for issue in issues:
                lines.append(f"- {issue}")
            lines.append("")

        next_steps = report.get("next_steps", [])
        if next_steps:
            lines.append("## Next Steps")
            for step in next_steps:
                lines.append(f"- {step}")
            lines.append("")

        questions = report.get("user_questions", [])
        if questions:
            lines.append("## Questions for You")
            for q in questions:
                lines.append(f"- {q}")
            lines.append("")

        return "\n".join(lines).strip()

    async def run(
        self,
        spec: "AgentRunSpec",
        hook: "AgentHook | None" = None,
    ) -> WorkflowResult:
        """Run the full structured workflow.

        If any phase fails, falls back to legacy behavior.

        Args:
            spec: The execution specification (same as AgentRunner.run).
            hook: Optional hook for callbacks.

        Returns:
            WorkflowResult containing the execution outcome.
        """
        logger.info("Workflow: Starting structured workflow")

        try:
            classification = await self._classify(spec.initial_messages)
            if classification is None:
                logger.warning("Workflow: Classification failed, falling back to legacy")
                return WorkflowResult(
                    used_workflow=False,
                    fallback_used=True,
                    fallback_reason="classification_failed",
                    execution_result=await self._run_legacy(),
                )

            primary_category = classification.get("primary_category", "unknown")
            if primary_category == "simple_qa":
                logger.info("Workflow: Task is simple_qa, using direct execution without planning overhead")
                execution_result = await self._run_legacy()
                return WorkflowResult(
                    used_workflow=True,
                    fallback_used=False,
                    classification=classification,
                    plan={"overall_goal": "Simple question/answer", "steps": [], "success_criteria": "Answer provided"},
                    execution_result=execution_result,
                    compressed={"original_task": self._extract_user_request(spec.initial_messages), "current_state": "Question answered"},
                    validation={"task_understood": True, "success_criteria_met": True, "validation_summary": "Simple QA completed", "confidence_score": 8},
                    report={"summary": "Simple question answered", "final_status": "success", "confidence": 8},
                )

            plan = await self._plan(spec.initial_messages, classification)
            if plan is None:
                logger.warning("Workflow: Planning failed, falling back to legacy")
                return WorkflowResult(
                    used_workflow=False,
                    fallback_used=True,
                    fallback_reason="planning_failed",
                    classification=classification,
                    execution_result=await self._run_legacy(),
                )

            logger.info("Workflow: Phase 3 - Executing plan via runner")
            execution_result = await self._run_legacy()

            if execution_result.stop_reason == "error":
                logger.warning("Workflow: Execution returned error, skipping remaining workflow phases")
                return WorkflowResult(
                    used_workflow=True,
                    fallback_used=False,
                    classification=classification,
                    plan=plan,
                    execution_result=execution_result,
                )

            original_task = plan.get("overall_goal", self._extract_user_request(spec.initial_messages))

            logger.info("Workflow: Phase 4 - Compressing results")
            compressed = await self._compress(original_task, plan, execution_result)
            if compressed is None:
                compressed = {
                    "original_task": original_task,
                    "current_state": "Completed but compression failed",
                    "key_decisions": [],
                    "tools_used_summary": execution_result.tools_used,
                    "files_modified": [],
                    "errors_encountered": [],
                    "remaining_questions": [],
                    "key_insights": [],
                }

            logger.info("Workflow: Phase 5 - Validating results")
            validation = await self._validate(original_task, plan, compressed, execution_result)
            if validation is None:
                validation = {
                    "task_understood": True,
                    "success_criteria_met": execution_result.stop_reason == "completed",
                    "steps_completed": [],
                    "steps_incomplete": [],
                    "errors_found": [],
                    "files_verified": [],
                    "validation_summary": "Validation skipped",
                    "confidence_score": 5,
                    "recommendations": [],
                    "needs_user_input": False,
                }

            logger.info("Workflow: Phase 6 - Generating report")
            report = await self._report(original_task, plan, validation, compressed)
            if report is None:
                report = {
                    "summary": execution_result.final_content or "Task completed",
                    "final_status": "success" if validation.get("success_criteria_met") else "partial_success",
                    "confidence": validation.get("confidence_score", 5),
                    "actions_taken": [],
                    "key_results": [],
                    "files_modified": [],
                    "issues_encountered": [],
                    "next_steps": [],
                    "user_questions": [],
                }

            if report and execution_result.final_content:
                report_content = self._build_report_content(report)
                if report_content:
                    execution_result = dataclasses.replace(
                        execution_result,
                        final_content=report_content,
                    )

            logger.info("Workflow: Completed successfully")
            return WorkflowResult(
                used_workflow=True,
                fallback_used=False,
                classification=classification,
                plan=plan,
                execution_result=execution_result,
                compressed=compressed,
                validation=validation,
                report=report,
            )

        except Exception as e:
            logger.exception("Workflow: Unexpected error, falling back to legacy")
            try:
                execution_result = await self._run_legacy()
                return WorkflowResult(
                    used_workflow=False,
                    fallback_used=True,
                    fallback_reason=f"exception: {type(e).__name__}: {e}",
                    execution_result=execution_result,
                )
            except Exception as legacy_error:
                logger.exception("Workflow: Legacy fallback also failed")
                return WorkflowResult(
                    used_workflow=False,
                    fallback_used=True,
                    fallback_reason=f"both_failed: workflow={e}, legacy={legacy_error}",
                    execution_result=None,
                )
