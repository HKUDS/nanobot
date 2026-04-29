"""Result Validator for validating execution results.

The Result Validator checks if the execution results meet the user's
requirements and identifies any partial successes or failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger

from nanobot.agent.workflow.executor import ExecutionResult
from nanobot.agent.workflow.router import TaskType


class ValidationStatus(Enum):
    """Status of the validation result."""
    
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    UNDETERMINED = "undetermined"


@dataclass
class ValidationResult:
    """Result of validating execution results.
    
    Contains the validation status and details about what passed/failed.
    """
    
    status: ValidationStatus = ValidationStatus.UNDETERMINED
    success: bool = False
    message: str = ""
    passed_checks: List[str] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    successful_results: List[Dict[str, Any]] = field(default_factory=list)
    failed_results: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def has_errors(self) -> bool:
        """Check if there are any errors.
        
        Returns:
            True if there are errors.
        """
        return len(self.errors) > 0 or self.status == ValidationStatus.FAILURE
    
    def has_partial_success(self) -> bool:
        """Check if this is a partial success.
        
        Returns:
            True if status is PARTIAL_SUCCESS.
        """
        return self.status == ValidationStatus.PARTIAL_SUCCESS
    
    def to_summary(self) -> str:
        """Generate a human-readable summary of the validation.
        
        Returns:
            A string summarizing the validation result.
        """
        lines = [f"Validation Status: {self.status.value.upper()}"]
        
        if self.message:
            lines.append(f"\n{self.message}")
        
        if self.passed_checks:
            lines.append(f"\n✅ Passed Checks ({len(self.passed_checks)}):")
            for check in self.passed_checks:
                lines.append(f"  - {check}")
        
        if self.failed_checks:
            lines.append(f"\n❌ Failed Checks ({len(self.failed_checks)}):")
            for check in self.failed_checks:
                lines.append(f"  - {check}")
        
        if self.warnings:
            lines.append(f"\n⚠️ Warnings ({len(self.warnings)}):")
            for warning in self.warnings:
                lines.append(f"  - {warning}")
        
        if self.errors:
            lines.append(f"\n💥 Errors ({len(self.errors)}):")
            for error in self.errors:
                lines.append(f"  - {error}")
        
        return "\n".join(lines)


class ResultValidator:
    """Validator for execution results.
    
    The Result Validator checks if the execution results meet the user's
    requirements. It identifies:
    - Complete success: All steps succeeded
    - Partial success: Some steps succeeded, some failed
    - Complete failure: Critical steps failed
    """
    
    def __init__(self, llm_provider: Any = None):
        """Initialize the Result Validator.
        
        Args:
            llm_provider: Optional LLM provider for advanced validation.
        """
        self.llm_provider = llm_provider
    
    async def validate(
        self,
        user_input: str,
        execution_results: List[ExecutionResult],
        task_type: TaskType = TaskType.UNKNOWN,
    ) -> ValidationResult:
        """Validate the execution results against the user's request.
        
        Args:
            user_input: The original user request.
            execution_results: List of execution results to validate.
            task_type: The type of task being validated.
            
        Returns:
            ValidationResult with the validation status and details.
        """
        logger.info("Validating {} execution results for task type: {}",
                    len(execution_results), task_type.value)
        
        result = ValidationResult()
        
        if not execution_results:
            result.status = ValidationStatus.UNDETERMINED
            result.success = False
            result.message = "No execution results to validate"
            return result
        
        successful = [r for r in execution_results if r.success]
        failed = [r for r in execution_results if not r.success]
        
        result.successful_results = [r.to_dict() for r in successful]
        result.failed_results = [r.to_dict() for r in failed]
        
        for r in successful:
            tool_name = r.tool_name or f"Step {r.step_index}"
            result.passed_checks.append(f"{tool_name}: executed successfully")
        
        for r in failed:
            tool_name = r.tool_name or f"Step {r.step_index}"
            error_msg = r.error_message or "Unknown error"
            result.failed_checks.append(f"{tool_name}: {error_msg[:100]}")
            if r.error_message:
                result.errors.append(f"{tool_name}: {r.error_message}")
        
        total_count = len(execution_results)
        success_count = len(successful)
        failure_count = len(failed)
        
        result.metadata = {
            "total_steps": total_count,
            "successful_steps": success_count,
            "failed_steps": failure_count,
            "task_type": task_type.value,
        }
        
        if failure_count == 0:
            result.status = ValidationStatus.SUCCESS
            result.success = True
            result.message = f"All {total_count} steps executed successfully"
            logger.info("Validation: SUCCESS - All {} steps passed", total_count)
        elif success_count > 0 and failure_count > 0:
            result.status = ValidationStatus.PARTIAL_SUCCESS
            result.success = False
            result.message = (
                f"Partial success: {success_count} of {total_count} steps succeeded, "
                f"{failure_count} failed"
            )
            result.warnings.append(
                f"Some steps failed. Review the failed checks for details."
            )
            logger.info("Validation: PARTIAL_SUCCESS - {}/{} steps passed",
                        success_count, total_count)
        else:
            result.status = ValidationStatus.FAILURE
            result.success = False
            result.message = f"All {total_count} steps failed"
            logger.warning("Validation: FAILURE - All {} steps failed", total_count)
        
        task_specific = self._validate_task_type(user_input, execution_results, task_type)
        if task_specific:
            result.message += f"\n\n{task_specific}"
        
        return result
    
    def _validate_task_type(
        self,
        user_input: str,
        execution_results: List[ExecutionResult],
        task_type: TaskType,
    ) -> Optional[str]:
        """Perform task-type specific validation.
        
        Args:
            user_input: The original user request.
            execution_results: List of execution results.
            task_type: The type of task.
            
        Returns:
            Optional string with task-specific validation notes.
        """
        if task_type == TaskType.PROJECT_ANALYSIS:
            return self._validate_project_analysis(execution_results)
        elif task_type == TaskType.FILE_OPERATION:
            return self._validate_file_operation(execution_results)
        elif task_type == TaskType.DEBUGGING:
            return self._validate_debugging(execution_results)
        elif task_type == TaskType.CODE_EXECUTION:
            return self._validate_code_execution(execution_results)
        
        return None
    
    def _validate_project_analysis(
        self,
        execution_results: List[ExecutionResult],
    ) -> str:
        """Validate project analysis results.
        
        Args:
            execution_results: List of execution results.
            
        Returns:
            Validation summary string.
        """
        list_dir_results = [r for r in execution_results if r.tool_name == "list_dir"]
        read_file_results = [r for r in execution_results if r.tool_name == "read_file"]
        glob_results = [r for r in execution_results if r.tool_name == "glob"]
        
        notes = []
        
        if list_dir_results:
            success = any(r.success for r in list_dir_results)
            notes.append(f"Directory listing: {'✅ Retrieved' if success else '❌ Failed'}")
        
        if glob_results:
            success = any(r.success for r in glob_results)
            notes.append(f"File pattern search: {'✅ Completed' if success else '❌ Failed'}")
        
        if read_file_results:
            success_count = sum(1 for r in read_file_results if r.success)
            total = len(read_file_results)
            notes.append(f"File reading: {success_count}/{total} files read successfully")
        
        return "\n".join(notes) if notes else ""
    
    def _validate_file_operation(
        self,
        execution_results: List[ExecutionResult],
    ) -> str:
        """Validate file operation results.
        
        Args:
            execution_results: List of execution results.
            
        Returns:
            Validation summary string.
        """
        write_ops = [r for r in execution_results if r.tool_name in ("write_file", "edit_file")]
        read_ops = [r for r in execution_results if r.tool_name == "read_file"]
        
        notes = []
        
        if write_ops:
            success = all(r.success for r in write_ops)
            notes.append(f"File modification: {'✅ Successful' if success else '⚠️ Some failed'}")
        
        if read_ops:
            success = all(r.success for r in read_ops)
            notes.append(f"File reading: {'✅ Successful' if success else '⚠️ Some failed'}")
        
        return "\n".join(notes) if notes else ""
    
    def _validate_debugging(
        self,
        execution_results: List[ExecutionResult],
    ) -> str:
        """Validate debugging results.
        
        Args:
            execution_results: List of execution results.
            
        Returns:
            Validation summary string.
        """
        read_ops = [r for r in execution_results if r.tool_name == "read_file"]
        edit_ops = [r for r in execution_results if r.tool_name == "edit_file"]
        exec_ops = [r for r in execution_results if r.tool_name == "exec"]
        
        notes = []
        
        if read_ops:
            success_count = sum(1 for r in read_ops if r.success)
            notes.append(f"Code analysis: {success_count}/{len(read_ops)} files read")
        
        if edit_ops:
            success_count = sum(1 for r in edit_ops if r.success)
            notes.append(f"Fix applied: {success_count}/{len(edit_ops)} modifications")
        
        if exec_ops:
            success_count = sum(1 for r in exec_ops if r.success)
            notes.append(f"Verification: {success_count}/{len(exec_ops)} tests/commands run")
        
        return "\n".join(notes) if notes else ""
    
    def _validate_code_execution(
        self,
        execution_results: List[ExecutionResult],
    ) -> str:
        """Validate code execution results.
        
        Args:
            execution_results: List of execution results.
            
        Returns:
            Validation summary string.
        """
        exec_ops = [r for r in execution_results if r.tool_name == "exec"]
        
        if not exec_ops:
            return ""
        
        success_count = sum(1 for r in exec_ops if r.success)
        total = len(exec_ops)
        
        if success_count == total:
            return f"✅ All {total} command(s) executed successfully"
        elif success_count > 0:
            return f"⚠️ {success_count}/{total} command(s) succeeded, check errors for failures"
        else:
            return f"❌ All {total} command(s) failed"
    
    def generate_error_summary(
        self,
        validation_result: ValidationResult,
    ) -> str:
        """Generate a user-friendly error summary.
        
        Args:
            validation_result: The validation result to summarize.
            
        Returns:
            A user-friendly string explaining what went wrong.
        """
        if validation_result.status == ValidationStatus.SUCCESS:
            return "All operations completed successfully."
        
        lines = []
        
        if validation_result.status == ValidationStatus.PARTIAL_SUCCESS:
            lines.append("⚠️ Partial Success")
            lines.append("Some operations completed successfully, but others failed.")
            lines.append("")
            lines.append("✅ Successful:")
            for check in validation_result.passed_checks:
                lines.append(f"  - {check}")
            lines.append("")
            lines.append("❌ Failed:")
            for check in validation_result.failed_checks:
                lines.append(f"  - {check}")
        
        elif validation_result.status == ValidationStatus.FAILURE:
            lines.append("❌ Operation Failed")
            lines.append("All critical operations failed.")
            lines.append("")
            lines.append("Errors:")
            for error in validation_result.errors:
                lines.append(f"  - {error}")
        
        else:
            lines.append("❓ Unknown Status")
            lines.append("The operation result could not be determined.")
            if validation_result.message:
                lines.append("")
                lines.append(validation_result.message)
        
        return "\n".join(lines)
