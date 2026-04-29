"""Plan Builder for creating execution plans based on task type.

The Plan Builder analyzes the user's request and creates a structured
execution plan that the Tool Executor can follow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger

from nanobot.agent.workflow.router import TaskType


class StepType(Enum):
    """Type of execution step."""
    
    TOOL_CALL = "tool_call"
    SKILL_LOAD = "skill_load"
    CONTEXT_GATHER = "context_gather"
    ANALYSIS = "analysis"
    VALIDATION = "validation"


@dataclass
class ExecutionStep:
    """A single step in an execution plan.
    
    Each step represents an action to be performed, such as a tool call
    or skill loading.
    """
    
    step_type: StepType
    tool_name: str = ""
    skill_name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    expected_output: str = ""
    critical: bool = True
    depends_on: List[int] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 2


@dataclass
class ExecutionPlan:
    """A complete execution plan for handling a user request.
    
    Contains a sequence of steps that should be executed to fulfill the request.
    """
    
    task_type: TaskType
    steps: List[ExecutionStep] = field(default_factory=list)
    summary: str = ""
    constraints: List[str] = field(default_factory=list)
    required_skills: List[str] = field(default_factory=list)
    estimated_complexity: str = "medium"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_step(self, step: ExecutionStep) -> None:
        """Add a step to the plan.
        
        Args:
            step: The ExecutionStep to add.
        """
        self.steps.append(step)
    
    def has_steps(self) -> bool:
        """Check if the plan has any steps.
        
        Returns:
            True if there are steps, False otherwise.
        """
        return len(self.steps) > 0


class PlanBuilder:
    """Builder for creating execution plans based on task type.
    
    The Plan Builder uses the identified task type to create an appropriate
    sequence of steps. It uses predefined patterns for common task types
    and can optionally use an LLM for more complex planning.
    """
    
    def __init__(
        self,
        llm_provider: Any = None,
        tools_registry: Any = None,
        skills_loader: Any = None,
    ):
        """Initialize the Plan Builder.
        
        Args:
            llm_provider: Optional LLM provider for advanced planning.
            tools_registry: The tool registry for available tools.
            skills_loader: The skills loader for available skills.
        """
        self.llm_provider = llm_provider
        self.tools_registry = tools_registry
        self.skills_loader = skills_loader
    
    async def build_plan(
        self,
        user_input: str,
        task_type: TaskType,
        conversation_history: List[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """Build an execution plan for the given task.
        
        Args:
            user_input: The user's input message.
            task_type: The identified task type.
            conversation_history: Optional conversation history.
            
        Returns:
            An ExecutionPlan with steps to execute.
        """
        logger.info("Building plan for task type: {}", task_type.value)
        
        plan = ExecutionPlan(task_type=task_type)
        
        try:
            if task_type == TaskType.PROJECT_ANALYSIS:
                plan = await self._build_project_analysis_plan(user_input)
            elif task_type == TaskType.CODE_ANALYSIS:
                plan = await self._build_code_analysis_plan(user_input)
            elif task_type == TaskType.FILE_OPERATION:
                plan = await self._build_file_operation_plan(user_input)
            elif task_type == TaskType.SEARCH:
                plan = await self._build_search_plan(user_input)
            elif task_type == TaskType.WEB_SEARCH:
                plan = await self._build_web_search_plan(user_input)
            elif task_type == TaskType.CODE_EXECUTION:
                plan = await self._build_code_execution_plan(user_input)
            elif task_type == TaskType.DEBUGGING:
                plan = await self._build_debugging_plan(user_input)
            elif task_type == TaskType.TESTING:
                plan = await self._build_testing_plan(user_input)
            elif task_type == TaskType.DOCUMENTATION:
                plan = await self._build_documentation_plan(user_input)
            else:
                plan = await self._build_general_plan(user_input, task_type)
        except Exception as e:
            logger.warning("Failed to build specific plan: {}, using default", e)
            plan = ExecutionPlan(task_type=task_type)
        
        return plan
    
    async def _build_project_analysis_plan(self, user_input: str) -> ExecutionPlan:
        """Build a plan for project analysis tasks.
        
        Project analysis typically involves:
        1. Listing the directory structure
        2. Reading key files (README, package.json, etc.)
        3. Analyzing the code structure
        
        Args:
            user_input: The user's input.
            
        Returns:
            ExecutionPlan for project analysis.
        """
        plan = ExecutionPlan(
            task_type=TaskType.PROJECT_ANALYSIS,
            summary="Analyze the project structure and key files",
            estimated_complexity="medium",
        )
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            description="List root directory structure",
            parameters={"path": ".", "recursive": True, "max_depth": 2},
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="glob",
            description="Find README and documentation files",
            parameters={"pattern": "**/README*"},
            critical=False,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="glob",
            description="Find config files",
            parameters={"pattern": "**/{package.json,pyproject.toml,setup.py,requirements.txt,Cargo.toml,go.mod}"},
            critical=False,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.ANALYSIS,
            description="Synthesize project overview from collected information",
            critical=True,
        ))
        
        plan.required_skills = []
        plan.constraints = [
            "Respect workspace boundaries",
            "Do not modify files during analysis",
            "Handle large directories gracefully",
        ]
        
        return plan
    
    async def _build_code_analysis_plan(self, user_input: str) -> ExecutionPlan:
        """Build a plan for code analysis tasks.
        
        Args:
            user_input: The user's input.
            
        Returns:
            ExecutionPlan for code analysis.
        """
        plan = ExecutionPlan(
            task_type=TaskType.CODE_ANALYSIS,
            summary="Analyze code to understand its structure and behavior",
            estimated_complexity="medium",
        )
        
        plan.add_step(ExecutionStep(
            step_type=StepType.CONTEXT_GATHER,
            description="Identify relevant files from user input",
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            description="Read the target file(s)",
            parameters={},
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.ANALYSIS,
            description="Analyze the code structure, logic, and patterns",
            critical=True,
        ))
        
        return plan
    
    async def _build_file_operation_plan(self, user_input: str) -> ExecutionPlan:
        """Build a plan for file operation tasks.
        
        Args:
            user_input: The user's input.
            
        Returns:
            ExecutionPlan for file operations.
        """
        plan = ExecutionPlan(
            task_type=TaskType.FILE_OPERATION,
            summary="Perform file operations (read, write, edit, etc.)",
            estimated_complexity="low",
        )
        
        plan.add_step(ExecutionStep(
            step_type=StepType.CONTEXT_GATHER,
            description="Identify the operation type and target file",
            critical=True,
        ))
        
        if "read" in user_input.lower():
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="read_file",
                description="Read the target file",
                parameters={},
                critical=True,
            ))
        elif "write" in user_input.lower() or "create" in user_input.lower():
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="write_file",
                description="Write to the target file",
                parameters={},
                critical=True,
            ))
        elif "edit" in user_input.lower() or "modify" in user_input.lower():
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="read_file",
                description="Read current file content",
                parameters={},
                critical=True,
            ))
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="edit_file",
                description="Edit the file",
                parameters={},
                critical=True,
            ))
        elif "list" in user_input.lower() or "ls" in user_input.lower():
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="list_dir",
                description="List directory contents",
                parameters={"path": "."},
                critical=True,
            ))
        
        plan.constraints = [
            "Always validate file paths before operations",
            "Respect workspace boundaries",
            "Create backups for critical modifications if needed",
        ]
        
        return plan
    
    async def _build_search_plan(self, user_input: str) -> ExecutionPlan:
        """Build a plan for search tasks.
        
        Args:
            user_input: The user's input.
            
        Returns:
            ExecutionPlan for search operations.
        """
        plan = ExecutionPlan(
            task_type=TaskType.SEARCH,
            summary="Search for files or content in the workspace",
            estimated_complexity="low",
        )
        
        plan.add_step(ExecutionStep(
            step_type=StepType.CONTEXT_GATHER,
            description="Determine search type (file name vs content)",
            critical=True,
        ))
        
        if "file" in user_input.lower() or "find" in user_input.lower():
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="glob",
                description="Search for files by pattern",
                parameters={},
                critical=True,
            ))
        else:
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="grep",
                description="Search for content in files",
                parameters={},
                critical=True,
            ))
        
        return plan
    
    async def _build_web_search_plan(self, user_input: str) -> ExecutionPlan:
        """Build a plan for web search tasks.
        
        Args:
            user_input: The user's input.
            
        Returns:
            ExecutionPlan for web search.
        """
        plan = ExecutionPlan(
            task_type=TaskType.WEB_SEARCH,
            summary="Search for information on the web",
            estimated_complexity="low",
        )
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="web_search",
            description="Search the web for relevant information",
            parameters={},
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="web_fetch",
            description="Fetch relevant pages for detailed information",
            parameters={},
            critical=False,
        ))
        
        return plan
    
    async def _build_code_execution_plan(self, user_input: str) -> ExecutionPlan:
        """Build a plan for code execution tasks.
        
        Args:
            user_input: The user's input.
            
        Returns:
            ExecutionPlan for code execution.
        """
        plan = ExecutionPlan(
            task_type=TaskType.CODE_EXECUTION,
            summary="Execute commands or scripts",
            estimated_complexity="medium",
        )
        
        plan.add_step(ExecutionStep(
            step_type=StepType.CONTEXT_GATHER,
            description="Identify the command to execute and its safety",
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.VALIDATION,
            description="Validate command safety and workspace boundaries",
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="exec",
            description="Execute the command",
            parameters={},
            critical=True,
        ))
        
        plan.constraints = [
            "Always validate commands before execution",
            "Respect workspace boundaries",
            "Use sandbox when configured",
        ]
        
        return plan
    
    async def _build_debugging_plan(self, user_input: str) -> ExecutionPlan:
        """Build a plan for debugging tasks.
        
        Args:
            user_input: The user's input.
            
        Returns:
            ExecutionPlan for debugging.
        """
        plan = ExecutionPlan(
            task_type=TaskType.DEBUGGING,
            summary="Debug and fix issues in the code",
            estimated_complexity="high",
        )
        
        plan.add_step(ExecutionStep(
            step_type=StepType.CONTEXT_GATHER,
            description="Understand the error and affected code",
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            description="Read relevant files",
            parameters={},
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.ANALYSIS,
            description="Analyze the root cause",
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="edit_file",
            description="Apply the fix",
            parameters={},
            critical=False,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.VALIDATION,
            description="Verify the fix works",
            critical=False,
        ))
        
        return plan
    
    async def _build_testing_plan(self, user_input: str) -> ExecutionPlan:
        """Build a plan for testing tasks.
        
        Args:
            user_input: The user's input.
            
        Returns:
            ExecutionPlan for testing.
        """
        plan = ExecutionPlan(
            task_type=TaskType.TESTING,
            summary="Create or run tests",
            estimated_complexity="medium",
        )
        
        plan.add_step(ExecutionStep(
            step_type=StepType.CONTEXT_GATHER,
            description="Identify what to test",
            critical=True,
        ))
        
        if "run" in user_input.lower() or "execute" in user_input.lower():
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="exec",
                description="Run the test command",
                parameters={},
                critical=True,
            ))
        else:
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="read_file",
                description="Read existing tests for reference",
                parameters={},
                critical=False,
            ))
            
            plan.add_step(ExecutionStep(
                step_type=StepType.TOOL_CALL,
                tool_name="write_file",
                description="Create test file",
                parameters={},
                critical=True,
            ))
        
        return plan
    
    async def _build_documentation_plan(self, user_input: str) -> ExecutionPlan:
        """Build a plan for documentation tasks.
        
        Args:
            user_input: The user's input.
            
        Returns:
            ExecutionPlan for documentation.
        """
        plan = ExecutionPlan(
            task_type=TaskType.DOCUMENTATION,
            summary="Create or improve documentation",
            estimated_complexity="medium",
        )
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            description="Read the code to document",
            parameters={},
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.ANALYSIS,
            description="Understand the code structure and purpose",
            critical=True,
        ))
        
        plan.add_step(ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="edit_file",
            description="Add documentation comments",
            parameters={},
            critical=True,
        ))
        
        return plan
    
    async def _build_general_plan(
        self,
        user_input: str,
        task_type: TaskType,
    ) -> ExecutionPlan:
        """Build a general plan for unrecognized task types.
        
        Args:
            user_input: The user's input.
            task_type: The identified task type.
            
        Returns:
            A default ExecutionPlan.
        """
        plan = ExecutionPlan(
            task_type=task_type,
            summary="General assistance task",
            estimated_complexity="low",
        )
        
        if task_type == TaskType.QUESTION_ANSWERING:
            plan.add_step(ExecutionStep(
                step_type=StepType.ANALYSIS,
                description="Answer the question based on available context",
                critical=True,
            ))
        elif task_type == TaskType.GENERAL_ASSISTANCE:
            plan.add_step(ExecutionStep(
                step_type=StepType.ANALYSIS,
                description="Provide general assistance",
                critical=True,
            ))
        
        return plan
