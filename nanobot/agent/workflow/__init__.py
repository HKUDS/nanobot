"""New Agent Workflow architecture for multi-stage processing.

This module implements a configurable, multi-stage agent workflow that can be
enabled/disabled via environment variable. The workflow includes:
- Task Router: Identify task type and intent
- Plan Builder: Create execution plan
- Tool Executor: Execute tool calls
- Context Compressor: Compress context for next iteration
- Result Validator: Validate execution results
- Report Renderer: Generate final report

The workflow can be enabled with NANOBOT_AGENT_WORKFLOW=1.
If the new workflow fails, it automatically falls back to the original loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from traceback import format_exc
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from nanobot.agent.workflow.router import TaskRouter, TaskType
from nanobot.agent.workflow.planner import PlanBuilder, ExecutionPlan
from nanobot.agent.workflow.executor import ToolExecutor, ExecutionResult
from nanobot.agent.workflow.compressor import ContextCompressor, CompressedContext
from nanobot.agent.workflow.validator import ResultValidator, ValidationResult
from nanobot.agent.workflow.renderer import ReportRenderer, RenderedReport


AGENT_WORKFLOW_ENV = "NANOBOT_AGENT_WORKFLOW"


def is_agent_workflow_enabled() -> bool:
    """Check if the new agent workflow is enabled via environment variable.
    
    Returns:
        True if NANOBOT_AGENT_WORKFLOW=1 is set, False otherwise.
    """
    return os.environ.get(AGENT_WORKFLOW_ENV, "0") == "1"


class WorkflowStage(Enum):
    """Enumeration of workflow stages for error tracking."""
    
    INITIALIZATION = "initialization"
    TASK_ROUTER = "task_router"
    PLAN_BUILDER = "plan_builder"
    TOOL_EXECUTOR = "tool_executor"
    CONTEXT_COMPRESSOR = "context_compressor"
    RESULT_VALIDATOR = "result_validator"
    REPORT_RENDERER = "report_renderer"


@dataclass
class WorkflowContext:
    """Context object passed through all workflow stages.
    
    This context carries the state from one stage to the next, allowing
    each stage to modify and extend the state as needed.
    """
    
    original_input: str
    task_type: TaskType = TaskType.UNKNOWN
    plan: Optional[ExecutionPlan] = None
    execution_results: List[ExecutionResult] = field(default_factory=list)
    compressed_context: Optional[CompressedContext] = None
    validation_result: Optional[ValidationResult] = None
    final_report: Optional[RenderedReport] = None
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[Tuple[WorkflowStage, Exception, str]] = field(default_factory=list)
    
    def add_error(self, stage: WorkflowStage, error: Exception) -> None:
        """Add an error that occurred during a workflow stage.
        
        Args:
            stage: The workflow stage where the error occurred.
            error: The exception that was raised.
        """
        traceback = format_exc()
        self.errors.append((stage, error, traceback))
        logger.warning(
            "Workflow error in stage [{}]: {}\n{}", 
            stage.value, 
            str(error)[:200],
            traceback
        )
    
    def has_errors(self) -> bool:
        """Check if any errors occurred during workflow execution.
        
        Returns:
            True if there are any errors, False otherwise.
        """
        return len(self.errors) > 0
    
    def get_last_error(self) -> Optional[Tuple[WorkflowStage, Exception, str]]:
        """Get the most recent error.
        
        Returns:
            Tuple of (stage, exception, traceback) or None if no errors.
        """
        return self.errors[-1] if self.errors else None
    
    def get_last_error_summary(self) -> Tuple[str, str]:
        """Get a summary of the last error for logging.
        
        Returns:
            Tuple of (stage_name, error_summary)
        """
        if not self.errors:
            return ("unknown", "No error recorded")
        stage, error, _ = self.errors[-1]
        stage_name = stage.value if isinstance(stage, WorkflowStage) else str(stage)
        error_msg = str(error)
        error_summary = error_msg[:100] + "..." if len(error_msg) > 100 else error_msg
        return (stage_name, error_summary)


@dataclass
class WorkflowResult:
    """Result of running the agent workflow.
    
    Contains the final output along with metadata about the execution.
    """
    
    success: bool
    content: str
    workflow_used: bool = True
    fallback_used: bool = False
    stage_results: Dict[str, Any] = field(default_factory=dict)
    errors: List[Tuple[WorkflowStage, Exception, str]] = field(default_factory=list)
    failed_stage: Optional[WorkflowStage] = None
    
    @property
    def partial_success(self) -> bool:
        """Check if the workflow partially succeeded (some tools worked, some failed).
        
        Returns:
            True if there are execution results with mixed success/failure.
        """
        if not self.stage_results.get("execution_results"):
            return False
        results = self.stage_results["execution_results"]
        has_success = any(r.success for r in results)
        has_failure = any(not r.success for r in results)
        return has_success and has_failure
    
    def get_failed_stage_name(self) -> str:
        """Get the name of the stage where workflow failed.
        
        Returns:
            Name of the failed stage or "unknown".
        """
        if self.failed_stage:
            return self.failed_stage.value
        if self.errors:
            stage, _, _ = self.errors[-1]
            return stage.value if isinstance(stage, WorkflowStage) else str(stage)
        return "unknown"
    
    def get_error_summary(self) -> str:
        """Get a summary of the last error.
        
        Returns:
            Error summary string.
        """
        if not self.errors:
            return "No error recorded"
        _, error, _ = self.errors[-1]
        error_msg = str(error)
        return error_msg[:150] + "..." if len(error_msg) > 150 else error_msg


class AgentWorkflow:
    """Main workflow orchestrator for the new agent loop architecture.
    
    This class orchestrates the multi-stage workflow:
    1. Task Router → Identify task type
    2. Plan Builder → Create execution plan
    3. Tool Executor → Execute tools based on plan
    4. Context Compressor → Compress context for next iteration
    5. Result Validator → Validate results
    6. Report Renderer → Generate final report
    
    The workflow can be configured to fall back to the original loop if
    any stage fails catastrophically.
    """
    
    def __init__(
        self,
        tools_registry: Any,
        skills_loader: Any,
        context_builder: Any,
        llm_provider: Any,
        workspace: Any,
        max_iterations: int = 10,
    ):
        """Initialize the agent workflow.
        
        Args:
            tools_registry: The ToolRegistry instance for tool execution.
            skills_loader: The SkillsLoader instance for skill loading.
            context_builder: The ContextBuilder instance for context building.
            llm_provider: The LLM provider for making API calls.
            workspace: The workspace path.
            max_iterations: Maximum number of workflow iterations.
        """
        self.tools_registry = tools_registry
        self.skills_loader = skills_loader
        self.context_builder = context_builder
        self.llm_provider = llm_provider
        self.workspace = workspace
        self.max_iterations = max_iterations
        
        self.router = TaskRouter(llm_provider=llm_provider)
        self.planner = PlanBuilder(
            llm_provider=llm_provider,
            tools_registry=tools_registry,
            skills_loader=skills_loader,
        )
        self.executor = ToolExecutor(tools_registry=tools_registry)
        self.compressor = ContextCompressor()
        self.validator = ResultValidator(llm_provider=llm_provider)
        self.renderer = ReportRenderer()
    
    async def run(
        self,
        user_input: str,
        conversation_history: List[Dict[str, Any]],
        on_progress: Optional[Callable[..., Any]] = None,
    ) -> WorkflowResult:
        """Execute the complete agent workflow.
        
        Args:
            user_input: The user's input message.
            conversation_history: Previous conversation messages.
            on_progress: Optional callback for progress updates.
            
        Returns:
            WorkflowResult containing the final output and metadata.
        """
        logger.info("Starting new agent workflow for input: {}", user_input[:80])
        
        ctx = WorkflowContext(original_input=user_input)
        stage_results: Dict[str, Any] = {}
        failed_stage: Optional[WorkflowStage] = None
        
        try:
            logger.info("Stage 1: Task Router - Analyzing task type")
            failed_stage = WorkflowStage.TASK_ROUTER
            ctx.task_type = await self.router.route(user_input, conversation_history)
            stage_results["task_type"] = ctx.task_type
            logger.info("Task identified as: {}", ctx.task_type.value)
            
            if on_progress:
                await on_progress(f"[Task Type: {ctx.task_type.value}]")
            
            logger.info("Stage 2: Plan Builder - Creating execution plan")
            failed_stage = WorkflowStage.PLAN_BUILDER
            ctx.plan = await self.planner.build_plan(
                user_input,
                ctx.task_type,
                conversation_history,
            )
            stage_results["plan"] = ctx.plan
            
            if ctx.plan and ctx.plan.steps:
                logger.info("Plan created with {} steps", len(ctx.plan.steps))
                if on_progress:
                    await on_progress(f"[Plan: {len(ctx.plan.steps)} steps]")
            else:
                logger.warning("No execution plan created, proceeding with default flow")
            
            logger.info("Stage 3: Tool Executor - Executing plan")
            failed_stage = WorkflowStage.TOOL_EXECUTOR
            if ctx.plan and ctx.plan.steps:
                for i, step in enumerate(ctx.plan.steps):
                    logger.info("Executing step {}: {}", i + 1, step.tool_name)
                    if on_progress:
                        await on_progress(f"[Executing: {step.tool_name}]")
                    
                    result = await self.executor.execute_step(step, conversation_history)
                    ctx.execution_results.append(result)
                    stage_results["execution_results"] = ctx.execution_results
                    
                    if not result.success:
                        logger.warning("Step {} failed: {}", i + 1, result.error_message)
                        if step.critical:
                            logger.error("Critical step failed, aborting workflow")
                            ctx.add_error(
                                WorkflowStage.TOOL_EXECUTOR, 
                                Exception(result.error_message or "Critical step failed")
                            )
                            break
            else:
                logger.info("No steps to execute, proceeding to validation")
            
            logger.info("Stage 4: Context Compressor - Compressing context")
            failed_stage = WorkflowStage.CONTEXT_COMPRESSOR
            ctx.compressed_context = await self.compressor.compress(
                conversation_history,
                ctx.execution_results,
            )
            stage_results["compressed_context"] = ctx.compressed_context
            
            logger.info("Stage 5: Result Validator - Validating results")
            failed_stage = WorkflowStage.RESULT_VALIDATOR
            ctx.validation_result = await self.validator.validate(
                user_input,
                ctx.execution_results,
                ctx.task_type,
            )
            stage_results["validation_result"] = ctx.validation_result
            
            logger.info(
                "Validation status: {}", 
                ctx.validation_result.status.value if ctx.validation_result else "unknown"
            )
            
            logger.info("Stage 6: Report Renderer - Generating final report")
            failed_stage = WorkflowStage.REPORT_RENDERER
            ctx.final_report = await self.renderer.render(
                user_input,
                ctx.task_type,
                ctx.plan,
                ctx.execution_results,
                ctx.validation_result,
            )
            stage_results["final_report"] = ctx.final_report
            
            final_content = ctx.final_report.content if ctx.final_report else "No result generated."
            
            failed_stage = None
            logger.info("Workflow completed successfully")
            return WorkflowResult(
                success=ctx.validation_result.success if ctx.validation_result else True,
                content=final_content,
                workflow_used=True,
                fallback_used=False,
                stage_results=stage_results,
                errors=ctx.errors,
                failed_stage=None,
            )
            
        except Exception as e:
            logger.error(
                "Workflow failed at stage [{}]: {}\n{}", 
                failed_stage.value if failed_stage else "unknown", 
                str(e)[:200],
                format_exc()
            )
            ctx.add_error(failed_stage or WorkflowStage.INITIALIZATION, e)
            
            return WorkflowResult(
                success=False,
                content=f"Workflow error at [{failed_stage.value if failed_stage else 'unknown'}]: {str(e)[:100]}...",
                workflow_used=True,
                fallback_used=True,
                stage_results=stage_results,
                errors=ctx.errors,
                failed_stage=failed_stage,
            )
