"""Agent workflow: structured task processing pipeline.

This module provides an optional, structured workflow for agent task processing:
- Task Classification: Analyze and categorize the user's request (guides tool selection)
- Planning: Create an execution plan (guides step-by-step execution)
- Execution: Run the plan WITH guidance from classification and plan
- Compression: Compress results to save context
- Validation: Verify the results meet requirements
- Reporting: Generate a final report

Enable with NANOBOT_AGENT_WORKFLOW=1 environment variable.
Automatically falls back to legacy behavior on errors.

Key difference from naive implementation:
- Classification results ACTUALLY determine:
  - Whether tools are needed (simple_qa = no tools)
  - Which tools are recommended
  - Max iterations based on complexity
- Plan results ACTUALLY guide execution:
  - Each step's guidance is injected into the context
  - Tools can be restricted per step
  - Validation occurs after each step
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.utils.helpers import build_assistant_message, truncate_text
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.runner import AgentRunResult, AgentRunSpec
    from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


_WORKFLOW_ENV_VAR = "NANOBOT_AGENT_WORKFLOW"

_CLASSIFY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "classify_task",
            "description": "Classify the user's task into predefined categories. This classification WILL affect execution: simple_qa disables tools, complexity affects max_iterations.",
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
                        "description": "Rough complexity estimate. LOW = ~2 iterations, MEDIUM = ~5 iterations, HIGH = ~10 iterations.",
                        "enum": ["low", "medium", "high"],
                    },
                    "needs_tools": {
                        "type": "boolean",
                        "description": "Whether this task REQUIRES tool calls. Simple questions about known info = False. Anything needing files/commands/web = True. This is a HARD constraint - if False, tools WILL be disabled.",
                    },
                    "recommended_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tools that would be most useful for this task. Empty means all tools allowed. Example: ['read_file', 'grep']",
                    },
                    "blocked_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tools that should NOT be used for this task. Example: ['exec'] if task is read-only.",
                    },
                    "suggested_max_iterations": {
                        "type": "integer",
                        "description": "Suggested maximum iterations based on complexity. Low=3, Medium=8, High=15.",
                    },
                },
                "required": ["primary_category", "reasoning", "estimated_complexity", "needs_tools"],
            },
        },
    }
]

_PLAN_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Create a detailed execution plan. This plan WILL be injected into the execution context and guide each step.",
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
                                "step_number": {
                                    "type": "integer",
                                    "description": "Sequential step number starting from 1.",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "What to do in this step.",
                                },
                                "execution_guidance": {
                                    "type": "string",
                                    "description": "Specific guidance for the agent during this step. This WILL be injected into the conversation context. Be specific about what to look for, what to avoid.",
                                },
                                "tools_allowed": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Tools allowed for THIS SPECIFIC STEP. Empty array = all tools allowed (from classification). This is a HARD constraint - only these tools will be available.",
                                },
                                "tools_preferred": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Tools to PREFER for this step (soft guidance, not enforced).",
                                },
                                "tools_avoid": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Tools to AVOID for this step (soft guidance, not enforced).",
                                },
                                "expected_outcome": {
                                    "type": "string",
                                    "description": "What success looks like for this step.",
                                },
                                "validation_query": {
                                    "type": "string",
                                    "description": "A question to ask the model to verify if this step is complete. Example: 'Did we find the file and read its contents?'",
                                },
                            },
                            "required": ["step_number", "description", "execution_guidance", "expected_outcome"],
                        },
                        "description": "Ordered list of execution steps. Each step's guidance WILL be injected during execution.",
                    },
                    "overall_tool_restrictions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tools that should be blocked for the ENTIRE task. Overrides individual step settings.",
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

_STEP_VALIDATION_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "validate_step",
            "description": "Validate if a specific execution step was completed successfully.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_complete": {
                        "type": "boolean",
                        "description": "Whether this step was successfully completed.",
                    },
                    "confidence": {
                        "type": "integer",
                        "description": "Number 0-10 indicating confidence in this assessment.",
                        "minimum": 0,
                        "maximum": 10,
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Explanation for why the step is or isn't complete.",
                    },
                    "next_action": {
                        "type": "string",
                        "description": "What to do next: 'proceed' to next step, 'retry' this step, 'adjust_plan', or 'fail_task'.",
                        "enum": ["proceed", "retry", "adjust_plan", "fail_task"],
                    },
                    "adjustments_needed": {
                        "type": "string",
                        "description": "If next_action is 'adjust_plan' or 'retry', what adjustments are needed.",
                    },
                },
                "required": ["step_complete", "confidence", "reasoning", "next_action"],
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
class StepExecutionResult:
    """Result of executing a single plan step."""

    step_number: int
    step_complete: bool
    messages: list[dict[str, Any]]
    tools_used: list[str]
    tool_events: list[dict[str, str]]
    usage: dict[str, int]
    stop_reason: str
    error: str | None = None
    validation_result: dict[str, Any] | None = None


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
        step_results: Results from individual step executions.
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
    step_results: list[StepExecutionResult] = dataclasses.field(default_factory=list)
    compressed: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    report: dict[str, Any] | None = None


class RestrictedToolRegistry(ToolRegistry):
    """A ToolRegistry wrapper that restricts available tools based on workflow guidance.

    This enables the TRUE CLOSED-LOOP behavior:
    - Classification can block certain tools
    - Plan steps can allow only specific tools
    - Simple_qa tasks can disable all tools
    """

    def __init__(
        self,
        original: ToolRegistry,
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
    ) -> None:
        """Initialize the restricted tool registry.

        Args:
            original: The original tool registry to wrap.
            allowed_tools: If provided, ONLY these tools will be available.
            blocked_tools: If provided, these tools will be unavailable.
                Takes precedence over allowed_tools.
        """
        super().__init__()
        self._original = original
        self._allowed_tools = allowed_tools
        self._blocked_tools = blocked_tools or []
        self._cached_definitions = None

    def _is_tool_allowed(self, name: str) -> bool:
        """Check if a tool is allowed under current restrictions."""
        if name in self._blocked_tools:
            return False
        if self._allowed_tools is not None:
            return name in self._allowed_tools
        return name in self._original._tools

    def get(self, name: str) -> Any:
        """Get a tool by name, respecting restrictions."""
        if not self._is_tool_allowed(name):
            return None
        return self._original.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered AND allowed."""
        return self._is_tool_allowed(name) and self._original.has(name)

    @property
    def tool_names(self) -> list[str]:
        """Get list of allowed tool names."""
        return [
            name
            for name in self._original.tool_names
            if self._is_tool_allowed(name)
        ]

    def __len__(self) -> int:
        return len(self.tool_names)

    def __contains__(self, name: str) -> bool:
        return self._is_tool_allowed(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions for allowed tools only."""
        if self._cached_definitions is not None:
            return self._cached_definitions

        original_defs = self._original.get_definitions()
        allowed_defs = []

        for schema in original_defs:
            name = ToolRegistry._schema_name(schema)
            if self._is_tool_allowed(name):
                allowed_defs.append(schema)

        self._cached_definitions = allowed_defs
        return allowed_defs

    def prepare_call(
        self,
        name: str,
        params: dict[str, Any],
    ) -> tuple[Any, dict[str, Any], str | None]:
        """Prepare a tool call, checking restrictions first."""
        if not self._is_tool_allowed(name):
            allowed = ", ".join(self.tool_names) if self.tool_names else "none"
            return None, params, (
                f"Error: Tool '{name}' is not available for this task. "
                f"Allowed tools: {allowed}"
            )
        return self._original.prepare_call(name, params)

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        """Execute a tool, checking restrictions first."""
        if not self._is_tool_allowed(name):
            allowed = ", ".join(self.tool_names) if self.tool_names else "none"
            return (
                f"Error: Tool '{name}' is not available for this task. "
                f"Allowed tools: {allowed}"
                "\n\n[Analyze the error above and try a different approach.]"
            )
        return await self._original.execute(name, params)


class AgentWorkflow:
    """Structured workflow for agent task processing with TRUE CLOSED-LOOP behavior.

    This class implements a 6-phase workflow where classification and planning
    ACTUALLY GUIDE the execution phase:

    1. Classification: Analyze and categorize
       - Determines: needs_tools, recommended_tools, blocked_tools, max_iterations
       - THESE ARE HARD CONSTRAINTS that affect execution

    2. Planning: Create step-by-step plan
       - Each step has: execution_guidance, tools_allowed, validation_query
       - THESE ARE INJECTED into execution context

    3. Guided Execution: Execute the plan with guidance
       - NOT just calling _run_legacy()
       - Tools are restricted based on classification + plan
       - Step guidance is injected before each step
       - Validation occurs after each step

    4. Compression: Compress results
    5. Validation: Verify overall results
    6. Reporting: Generate final report

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
        """Extract the user's request from the message list."""
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
        """Extract a summary of the conversation context."""
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
        """Convert message list to a readable text format."""
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

    def _build_step_context_injection(
        self,
        step: dict[str, Any],
        overall_plan: dict[str, Any],
        classification: dict[str, Any],
    ) -> str:
        """Build the context injection for a specific step.

        This is INJECTED into the conversation before executing the step,
        providing TRUE GUIDANCE from the plan.
        """
        lines = ["---"]
        lines.append("## WORKFLOW GUIDANCE - DO NOT IGNORE")
        lines.append("")

        lines.append("### Task Classification")
        lines.append(f"- Category: {classification.get('primary_category', 'unknown')}")
        lines.append(f"- Complexity: {classification.get('estimated_complexity', 'unknown')}")

        needs_tools = classification.get('needs_tools', True)
        lines.append(f"- Tools Required: {'Yes' if needs_tools else 'No'}")

        if classification.get('recommended_tools'):
            lines.append(f"- Recommended Tools: {', '.join(classification['recommended_tools'])}")
        if classification.get('blocked_tools'):
            lines.append(f"- Blocked Tools: {', '.join(classification['blocked_tools'])}")

        lines.append("")
        lines.append("### Execution Plan Context")
        lines.append(f"- Overall Goal: {overall_plan.get('overall_goal', 'Unknown')}")
        total_steps = len(overall_plan.get('steps', []))
        lines.append(f"- Progress: Step {step.get('step_number', 1)} of {total_steps}")
        lines.append("")

        lines.append("### Current Step Guidance")
        lines.append(f"- Step: {step.get('description', 'Unknown')}")
        lines.append(f"- Expected Outcome: {step.get('expected_outcome', 'Unknown')}")

        execution_guidance = step.get('execution_guidance')
        if execution_guidance:
            lines.append(f"- Guidance: {execution_guidance}")

        if step.get('tools_allowed'):
            lines.append(f"- Tools Allowed (HARD CONSTRAINT - only these): {', '.join(step['tools_allowed'])}")
        if step.get('tools_preferred'):
            lines.append(f"- Tools Preferred: {', '.join(step['tools_preferred'])}")
        if step.get('tools_avoid'):
            lines.append(f"- Tools to Avoid: {', '.join(step['tools_avoid'])}")

        lines.append("")
        lines.append("### Validation (after execution)")
        validation_query = step.get('validation_query')
        if validation_query:
            lines.append(f"- Validation Question: {validation_query}")

        lines.append("")
        lines.append("Execute this step according to the guidance above.")
        lines.append("---")

        return "\n".join(lines)

    def _inject_step_guidance(
        self,
        messages: list[dict[str, Any]],
        step_context: str,
    ) -> list[dict[str, Any]]:
        """Inject step guidance into the message list.

        The guidance is appended to the last user message, or added as a new user message.
        """
        if not messages:
            return [{"role": "user", "content": step_context}]

        messages_copy = [dict(m) for m in messages]
        last_msg = messages_copy[-1]

        if last_msg.get("role") == "user":
            existing_content = last_msg.get("content", "")
            if isinstance(existing_content, str):
                last_msg["content"] = f"{existing_content}\n\n{step_context}"
            elif isinstance(existing_content, list):
                existing_content.append({"type": "text", "text": step_context})
        else:
            messages_copy.append({"role": "user", "content": step_context})

        return messages_copy

    def _create_restricted_tools(
        self,
        original_tools: ToolRegistry,
        classification: dict[str, Any],
        step: dict[str, Any] | None = None,
        overall_plan: dict[str, Any] | None = None,
    ) -> RestrictedToolRegistry:
        """Create a RestrictedToolRegistry based on classification and plan.

        This is a KEY part of the TRUE CLOSED-LOOP:
        - If classification says needs_tools=False, ALL tools are blocked
        - classification.recommended_tools = allowed tools (if specified)
        - classification.blocked_tools = blocked tools
        - step.tools_allowed = further restriction per step
        - overall_plan.overall_tool_restrictions = additional blocks
        """
        allowed_tools: list[str] | None = None
        blocked_tools: list[str] = []

        if not classification.get("needs_tools", True):
            blocked_tools = list(original_tools.tool_names)
            logger.info("Workflow: Tools DISABLED per classification (needs_tools=False)")
        else:
            recommended = classification.get("recommended_tools", [])
            if recommended:
                allowed_tools = list(recommended)
                logger.info("Workflow: Tools restricted to: {}", recommended)

            blocked = classification.get("blocked_tools", [])
            if blocked:
                blocked_tools.extend(blocked)
                logger.info("Workflow: Tools blocked: {}", blocked)

        if overall_plan:
            plan_restrictions = overall_plan.get("overall_tool_restrictions", [])
            if plan_restrictions:
                blocked_tools.extend(plan_restrictions)
                logger.info("Workflow: Additional tools blocked by plan: {}", plan_restrictions)

        if step:
            step_allowed = step.get("tools_allowed", [])
            if step_allowed:
                if allowed_tools is not None:
                    allowed_tools = [t for t in allowed_tools if t in step_allowed]
                else:
                    allowed_tools = list(step_allowed)
                logger.info("Workflow: Step {} tools restricted to: {}", step.get('step_number'), step_allowed)

        blocked_tools = list(dict.fromkeys(blocked_tools))

        return RestrictedToolRegistry(
            original=original_tools,
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools if blocked_tools else None,
        )

    async def _classify(self, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Phase 1: Classify the user's task.

        CRITICAL: The classification result WILL affect execution:
        - needs_tools: False = ALL tools blocked
        - recommended_tools: only these tools allowed
        - blocked_tools: these tools unavailable
        - suggested_max_iterations: overrides spec.max_iterations
        """
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
            max_tokens=1024,
            temperature=0.0,
        )

        if result:
            primary_category = result.get("primary_category", "unknown")
            estimated_complexity = result.get("estimated_complexity", "unknown")
            needs_tools = result.get("needs_tools", True)

            if primary_category == "simple_qa" and "needs_tools" not in result:
                result["needs_tools"] = False
                needs_tools = False

            if "suggested_max_iterations" not in result:
                complexity_map = {"low": 3, "medium": 8, "high": 15}
                result["suggested_max_iterations"] = complexity_map.get(estimated_complexity, 5)

            logger.info(
                "Workflow: Task classified as '{}' (complexity={}, needs_tools={})",
                primary_category,
                estimated_complexity,
                needs_tools,
            )
        return result

    async def _plan(
        self,
        messages: list[dict[str, Any]],
        classification: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Phase 2: Create an execution plan.

        CRITICAL: The plan WILL guide execution:
        - Each step's execution_guidance is INJECTED into context
        - Each step's tools_allowed is a HARD constraint
        - Each step's validation_query is used after execution
        """
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
            steps = result.get("steps", [])
            for i, step in enumerate(steps):
                if "step_number" not in step:
                    step["step_number"] = i + 1

            logger.info(
                "Workflow: Plan created with {} steps",
                len(steps),
            )
        return result

    async def _validate_step(
        self,
        step: dict[str, Any],
        execution_messages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Validate if a step was completed successfully."""
        validation_query = step.get("validation_query", "Was this step completed successfully?")
        conversation_text = self._messages_to_text(execution_messages[-10:])

        validation_messages = [
            {
                "role": "system",
                "content": (
                    "You are a step validator. Your job is to determine if the execution step "
                    "was completed successfully based on the conversation history."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Step Description\n{step.get('description', 'Unknown')}\n\n"
                    f"## Expected Outcome\n{step.get('expected_outcome', 'Unknown')}\n\n"
                    f"## Validation Question\n{validation_query}\n\n"
                    f"## Conversation History\n{conversation_text}\n\n"
                    "Use the validate_step tool to determine if this step was completed successfully."
                ),
            },
        ]

        result = await self._call_tool_llm(
            validation_messages,
            _STEP_VALIDATION_TOOL,
            max_tokens=512,
            temperature=0.0,
        )

        if result:
            logger.info(
                "Workflow: Step {} validation: complete={}, confidence={}, next_action={}",
                step.get("step_number"),
                result.get("step_complete"),
                result.get("confidence"),
                result.get("next_action"),
            )
        return result

    async def _execute_step(
        self,
        spec: "AgentRunSpec",
        step: dict[str, Any],
        overall_plan: dict[str, Any],
        classification: dict[str, Any],
        messages_so_far: list[dict[str, Any]],
        hook: "AgentHook | None" = None,
    ) -> StepExecutionResult:
        """Execute a single step with full guidance from classification and plan.

        This is the HEART of the TRUE CLOSED-LOOP:
        1. Create RestrictedToolRegistry based on classification + step
        2. Inject step guidance into messages
        3. Execute the step
        4. Validate the step result

        This is NOT just calling _run_legacy() - tools are restricted,
        guidance is injected, and validation occurs.
        """
        from nanobot.agent.runner import AgentRunner, AgentRunResult

        step_number = step.get("step_number", 1)
        logger.info("Workflow: Executing step {}", step_number)

        step_context = self._build_step_context_injection(step, overall_plan, classification)
        step_messages = self._inject_step_guidance(messages_so_far, step_context)

        restricted_tools = self._create_restricted_tools(
            spec.tools,
            classification,
            step=step,
            overall_plan=overall_plan,
        )

        suggested_max_iterations = classification.get("suggested_max_iterations")
        step_max_iterations = suggested_max_iterations if suggested_max_iterations else spec.max_iterations

        step_spec = dataclasses.replace(
            spec,
            initial_messages=step_messages,
            tools=restricted_tools,
            max_iterations=min(step_max_iterations, 3),
        )

        runner = AgentRunner(self.provider)

        try:
            result: AgentRunResult = await runner._run_legacy(step_spec, hook)

            validation = None
            if result.stop_reason != "error":
                validation = await self._validate_step(step, result.messages)

            step_complete = False
            if validation:
                step_complete = validation.get("step_complete", False)

            return StepExecutionResult(
                step_number=step_number,
                step_complete=step_complete,
                messages=result.messages,
                tools_used=result.tools_used,
                tool_events=result.tool_events,
                usage=result.usage,
                stop_reason=result.stop_reason,
                error=result.error,
                validation_result=validation,
            )

        except Exception as e:
            logger.exception("Workflow: Step {} execution failed", step_number)
            return StepExecutionResult(
                step_number=step_number,
                step_complete=False,
                messages=messages_so_far,
                tools_used=[],
                tool_events=[],
                usage={},
                stop_reason="error",
                error=str(e),
                validation_result=None,
            )

    async def _execute_guided(
        self,
        spec: "AgentRunSpec",
        classification: dict[str, Any],
        plan: dict[str, Any],
        hook: "AgentHook | None" = None,
    ) -> tuple["AgentRunResult", list[StepExecutionResult]]:
        """Execute the task with FULL guidance from classification and plan.

        This is the TRUE CLOSED-LOOP execution:
        - Each step has restricted tools
        - Each step has injected guidance
        - Each step is validated
        - We don't just call _run_legacy() once

        Returns:
            Tuple of (final aggregated result, list of step results)
        """
        from nanobot.agent.runner import AgentRunResult

        steps = plan.get("steps", [])
        if not steps:
            logger.warning("Workflow: Plan has no steps, falling back to single-step execution")
            return await self._run_legacy(), []

        step_results: list[StepExecutionResult] = []
        current_messages = list(spec.initial_messages)
        total_tools_used: list[str] = []
        total_tool_events: list[dict[str, str]] = []
        total_usage: dict[str, int] = {}
        final_stop_reason = "completed"
        final_error: str | None = None

        for step in steps:
            step_result = await self._execute_step(
                spec,
                step,
                plan,
                classification,
                current_messages,
                hook,
            )
            step_results.append(step_result)

            total_tools_used.extend(step_result.tools_used)
            total_tool_events.extend(step_result.tool_events)
            for key, value in step_result.usage.items():
                total_usage[key] = total_usage.get(key, 0) + value

            current_messages = step_result.messages

            if step_result.stop_reason == "error":
                final_stop_reason = "error"
                final_error = step_result.error
                logger.warning("Workflow: Step {} failed, stopping execution", step_result.step_number)
                break

            validation = step_result.validation_result
            if validation:
                next_action = validation.get("next_action", "proceed")

                if next_action == "fail_task":
                    final_stop_reason = "error"
                    final_error = validation.get("adjustments_needed", "Task failed validation")
                    logger.warning("Workflow: Step validation indicated task failure")
                    break

                elif next_action == "adjust_plan":
                    logger.info("Workflow: Step validation suggested plan adjustment, but continuing")

                elif next_action == "retry":
                    logger.info("Workflow: Step validation suggested retry, but continuing to next step")

        final_content = current_messages[-1].get("content", "") if current_messages else ""
        if isinstance(final_content, list):
            text_parts = [
                block.get("text", "")
                for block in final_content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            final_content = " ".join(text_parts)

        aggregated_result = AgentRunResult(
            final_content=final_content,
            messages=current_messages,
            tools_used=total_tools_used,
            usage=total_usage,
            stop_reason=final_stop_reason,
            error=final_error,
            tool_events=total_tool_events,
            had_injections=False,
        )

        return aggregated_result, step_results

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
        """Convert the report dict to a user-facing string."""
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
        """Run the full structured workflow with TRUE CLOSED-LOOP behavior.

        CRITICAL DIFFERENCE from naive implementation:
        - Classification results ACTUALLY determine tool availability
        - Plan results ACTUALLY guide each execution step
        - We do NOT just call _run_legacy() and then summarize
        - Each step has: restricted tools, injected guidance, validation

        If any phase fails, falls back to legacy behavior.

        Args:
            spec: The execution specification.
            hook: Optional hook for callbacks.

        Returns:
            WorkflowResult containing the execution outcome.
        """
        logger.info("Workflow: Starting structured workflow (TRUE CLOSED-LOOP)")

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
            needs_tools = classification.get("needs_tools", True)

            if primary_category == "simple_qa" and not needs_tools:
                logger.info("Workflow: Task is simple_qa with needs_tools=False - using direct LLM call without tools")

                from nanobot.agent.runner import AgentRunResult

                try:
                    response = await self.provider.chat_with_retry(
                        messages=spec.initial_messages,
                        tools=[],
                        model=spec.model,
                        max_tokens=spec.max_tokens or 1024,
                        temperature=spec.temperature,
                    )

                    final_content = response.content or ""

                    direct_result = AgentRunResult(
                        final_content=final_content,
                        messages=spec.initial_messages + [
                            {"role": "assistant", "content": final_content}
                        ],
                        tools_used=[],
                        usage=self._usage_dict(response.usage) if response.usage else {},
                        stop_reason="completed",
                        error=None,
                        tool_events=[],
                        had_injections=False,
                    )

                    return WorkflowResult(
                        used_workflow=True,
                        fallback_used=False,
                        classification=classification,
                        plan={
                            "overall_goal": "Simple question/answer without tools",
                            "steps": [],
                            "success_criteria": "Answer provided",
                        },
                        execution_result=direct_result,
                        compressed={
                            "original_task": self._extract_user_request(spec.initial_messages),
                            "current_state": "Question answered directly without tools",
                            "key_decisions": ["Used direct LLM call per simple_qa classification"],
                            "tools_used_summary": [],
                            "files_modified": [],
                            "errors_encountered": [],
                            "remaining_questions": [],
                            "key_insights": [],
                        },
                        validation={
                            "task_understood": True,
                            "success_criteria_met": True,
                            "steps_completed": ["Direct answer provided"],
                            "steps_incomplete": [],
                            "errors_found": [],
                            "files_verified": [],
                            "validation_summary": "Simple QA completed with direct LLM call",
                            "confidence_score": 8,
                            "recommendations": [],
                            "needs_user_input": False,
                        },
                        report={
                            "summary": final_content,
                            "final_status": "success",
                            "confidence": 8,
                        },
                    )

                except Exception as e:
                    logger.warning("Workflow: Simple QA direct call failed: {}, falling back", e)

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

            logger.info("Workflow: Phase 3 - Guided Execution (TRUE CLOSED-LOOP)")
            execution_result, step_results = await self._execute_guided(
                spec,
                classification,
                plan,
                hook,
            )

            if execution_result.stop_reason == "error":
                logger.warning("Workflow: Execution returned error, skipping remaining workflow phases")
                return WorkflowResult(
                    used_workflow=True,
                    fallback_used=False,
                    classification=classification,
                    plan=plan,
                    execution_result=execution_result,
                    step_results=step_results,
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

            logger.info("Workflow: Completed successfully (TRUE CLOSED-LOOP)")
            return WorkflowResult(
                used_workflow=True,
                fallback_used=False,
                classification=classification,
                plan=plan,
                execution_result=execution_result,
                step_results=step_results,
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

    @staticmethod
    def _usage_dict(usage: Any) -> dict[str, int]:
        """Convert usage object to dict."""
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return dict(usage)
        result: dict[str, int] = {}
        for attr in ["input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens"]:
            if hasattr(usage, attr):
                val = getattr(usage, attr)
                if isinstance(val, int):
                    result[attr] = val
        return result
