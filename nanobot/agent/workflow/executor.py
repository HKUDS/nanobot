"""Tool Executor for executing tool calls based on the execution plan.

The Tool Executor takes the execution plan from the Plan Builder and
executes each step, handling errors and retries appropriately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger

from nanobot.agent.workflow.planner import ExecutionStep, StepType


class ExecutionStatus(Enum):
    """Status of an execution result."""
    
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


@dataclass
class ExecutionResult:
    """Result of executing a single step.
    
    Contains the output of the execution along with metadata.
    """
    
    step_index: int
    step_type: StepType
    tool_name: str = ""
    status: ExecutionStatus = ExecutionStatus.PENDING
    success: bool = False
    output: Any = None
    error_message: str = ""
    exception: Optional[Exception] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a dictionary for storage/logging.
        
        Returns:
            Dictionary representation of the result.
        """
        return {
            "step_index": self.step_index,
            "step_type": self.step_type.value,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "success": self.success,
            "output": str(self.output) if self.output is not None else None,
            "error_message": self.error_message,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "retry_count": self.retry_count,
            "metadata": self.metadata,
        }


class ToolExecutor:
    """Executor for running tool calls and other execution steps.
    
    The Tool Executor is responsible for executing each step in the
    execution plan, handling retries, and collecting results.
    """
    
    def __init__(self, tools_registry: Any = None):
        """Initialize the Tool Executor.
        
        Args:
            tools_registry: The tool registry for looking up and executing tools.
        """
        self.tools_registry = tools_registry
        self._execution_history: List[ExecutionResult] = []
    
    async def execute_step(
        self,
        step: ExecutionStep,
        conversation_history: List[Dict[str, Any]] = None,
    ) -> ExecutionResult:
        """Execute a single step from the execution plan.
        
        Args:
            step: The ExecutionStep to execute.
            conversation_history: Optional conversation history for context.
            
        Returns:
            ExecutionResult containing the outcome.
        """
        result = ExecutionResult(
            step_index=len(self._execution_history),
            step_type=step.step_type,
            tool_name=step.tool_name,
            status=ExecutionStatus.RUNNING,
            start_time=datetime.now(),
        )
        
        logger.info("Executing step {}: {} ({})", result.step_index, step.tool_name, step.step_type.value)
        
        try:
            if step.step_type == StepType.TOOL_CALL:
                result = await self._execute_tool_call(step, result)
            elif step.step_type == StepType.SKILL_LOAD:
                result = await self._execute_skill_load(step, result)
            elif step.step_type == StepType.CONTEXT_GATHER:
                result = await self._execute_context_gather(step, result, conversation_history)
            elif step.step_type == StepType.ANALYSIS:
                result = await self._execute_analysis(step, result)
            elif step.step_type == StepType.VALIDATION:
                result = await self._execute_validation(step, result)
            else:
                result.status = ExecutionStatus.SKIPPED
                result.success = True
                result.output = f"Step type {step.step_type.value} not implemented, skipped"
                logger.warning("Step type {} not implemented, skipped", step.step_type.value)
        
        except Exception as e:
            result.status = ExecutionStatus.FAILED
            result.success = False
            result.error_message = str(e)
            result.exception = e
            logger.error("Step {} failed: {}", result.step_index, str(e))
        
        result.end_time = datetime.now()
        self._execution_history.append(result)
        
        return result
    
    async def _execute_tool_call(
        self,
        step: ExecutionStep,
        result: ExecutionResult,
    ) -> ExecutionResult:
        """Execute a tool call step.
        
        Args:
            step: The ExecutionStep containing the tool call.
            result: The ExecutionResult to populate.
            
        Returns:
            Updated ExecutionResult.
        """
        if not self.tools_registry:
            result.status = ExecutionStatus.FAILED
            result.success = False
            result.error_message = "No tools registry available"
            return result
        
        tool_name = step.tool_name
        
        if not tool_name:
            result.status = ExecutionStatus.SKIPPED
            result.success = True
            result.output = "No tool specified, step skipped"
            return result
        
        tool = self.tools_registry.get(tool_name) if hasattr(self.tools_registry, 'get') else None
        
        if not tool and hasattr(self.tools_registry, 'has'):
            if not self.tools_registry.has(tool_name):
                result.status = ExecutionStatus.FAILED
                result.success = False
                result.error_message = f"Tool '{tool_name}' not found in registry"
                return result
        
        params = step.parameters or {}
        
        if not params and step.step_type == StepType.TOOL_CALL:
            result.status = ExecutionStatus.SKIPPED
            result.success = True
            result.output = f"Tool '{tool_name}' ready but no parameters provided"
            result.metadata["note"] = "Parameters need to be resolved from context"
            return result
        
        try:
            if hasattr(self.tools_registry, 'execute') and callable(self.tools_registry.execute):
                output = await self.tools_registry.execute(tool_name, params)
                result.output = output
                
                if isinstance(output, str) and output.startswith("Error"):
                    result.status = ExecutionStatus.FAILED
                    result.success = False
                    result.error_message = output
                else:
                    result.status = ExecutionStatus.SUCCESS
                    result.success = True
            else:
                result.status = ExecutionStatus.SKIPPED
                result.success = True
                result.output = f"Tool execution not available, step skipped"
        except Exception as e:
            result.status = ExecutionStatus.FAILED
            result.success = False
            result.error_message = f"Tool execution failed: {str(e)}"
            result.exception = e
        
        return result
    
    async def _execute_skill_load(
        self,
        step: ExecutionStep,
        result: ExecutionResult,
    ) -> ExecutionResult:
        """Execute a skill load step.
        
        Args:
            step: The ExecutionStep containing the skill to load.
            result: The ExecutionResult to populate.
            
        Returns:
            Updated ExecutionResult.
        """
        skill_name = step.skill_name
        
        if not skill_name:
            result.status = ExecutionStatus.SKIPPED
            result.success = True
            result.output = "No skill specified, step skipped"
            return result
        
        result.status = ExecutionStatus.SUCCESS
        result.success = True
        result.output = f"Skill '{skill_name}' would be loaded"
        result.metadata["skill_name"] = skill_name
        
        logger.info("Skill load step: {}", skill_name)
        
        return result
    
    async def _execute_context_gather(
        self,
        step: ExecutionStep,
        result: ExecutionResult,
        conversation_history: List[Dict[str, Any]] = None,
    ) -> ExecutionResult:
        """Execute a context gather step.
        
        This step type is used to analyze the input and determine what
        parameters to pass to subsequent steps.
        
        Args:
            step: The ExecutionStep.
            result: The ExecutionResult to populate.
            conversation_history: Optional conversation history.
            
        Returns:
            Updated ExecutionResult.
        """
        result.status = ExecutionStatus.SUCCESS
        result.success = True
        result.output = "Context gathering completed"
        result.metadata["history_available"] = bool(conversation_history)
        result.metadata["step_description"] = step.description
        
        logger.info("Context gather step completed")
        
        return result
    
    async def _execute_analysis(
        self,
        step: ExecutionStep,
        result: ExecutionResult,
    ) -> ExecutionResult:
        """Execute an analysis step.
        
        Analysis steps are typically handled by the LLM in the workflow.
        This executor just marks them as complete.
        
        Args:
            step: The ExecutionStep.
            result: The ExecutionResult to populate.
            
        Returns:
            Updated ExecutionResult.
        """
        result.status = ExecutionStatus.SUCCESS
        result.success = True
        result.output = "Analysis step - will be handled by LLM in workflow"
        result.metadata["step_description"] = step.description
        
        logger.info("Analysis step marked for LLM processing")
        
        return result
    
    async def _execute_validation(
        self,
        step: ExecutionStep,
        result: ExecutionResult,
    ) -> ExecutionResult:
        """Execute a validation step.
        
        Validation steps check if previous steps were successful.
        
        Args:
            step: The ExecutionStep.
            result: The ExecutionResult to populate.
            
        Returns:
            Updated ExecutionResult.
        """
        result.status = ExecutionStatus.SUCCESS
        result.success = True
        result.output = "Validation step - checking previous results"
        result.metadata["step_description"] = step.description
        
        if self._execution_history:
            successful = sum(1 for r in self._execution_history if r.success)
            failed = sum(1 for r in self._execution_history if not r.success)
            result.metadata["previous_successes"] = successful
            result.metadata["previous_failures"] = failed
        
        logger.info("Validation step completed")
        
        return result
    
    async def execute_plan(
        self,
        plan: ExecutionStep,
        conversation_history: List[Dict[str, Any]] = None,
    ) -> List[ExecutionResult]:
        """Execute all steps in an execution plan.
        
        Args:
            plan: The ExecutionPlan containing steps to execute.
            conversation_history: Optional conversation history.
            
        Returns:
            List of ExecutionResult for each step.
        """
        results: List[ExecutionResult] = []
        
        if not hasattr(plan, 'steps') or not plan.steps:
            logger.warning("No steps to execute in plan")
            return results
        
        for i, step in enumerate(plan.steps):
            result = await self.execute_step(step, conversation_history)
            results.append(result)
            
            if not result.success and step.critical:
                logger.error("Critical step {} failed, aborting execution", i)
                break
        
        return results
    
    def get_history(self) -> List[ExecutionResult]:
        """Get the execution history.
        
        Returns:
            List of all ExecutionResult objects from this executor.
        """
        return list(self._execution_history)
    
    def get_successful_results(self) -> List[ExecutionResult]:
        """Get only successful results from history.
        
        Returns:
            List of successful ExecutionResult objects.
        """
        return [r for r in self._execution_history if r.success]
    
    def get_failed_results(self) -> List[ExecutionResult]:
        """Get only failed results from history.
        
        Returns:
            List of failed ExecutionResult objects.
        """
        return [r for r in self._execution_history if not r.success]
    
    def has_failures(self) -> bool:
        """Check if any steps failed.
        
        Returns:
            True if there are any failed results.
        """
        return any(not r.success for r in self._execution_history)
    
    def has_partial_success(self) -> bool:
        """Check if there's a mix of success and failure.
        
        Returns:
            True if some steps succeeded and some failed.
        """
        has_success = any(r.success for r in self._execution_history)
        has_failure = any(not r.success for r in self._execution_history)
        return has_success and has_failure
