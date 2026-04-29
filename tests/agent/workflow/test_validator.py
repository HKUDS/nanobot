"""Tests for the Result Validator module."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from nanobot.agent.workflow.validator import (
    ResultValidator,
    ValidationResult,
    ValidationStatus,
)
from nanobot.agent.workflow.executor import ExecutionResult, ExecutionStatus
from nanobot.agent.workflow.planner import StepType
from nanobot.agent.workflow.router import TaskType


class TestValidationStatus:
    """Tests for ValidationStatus enum."""
    
    def test_validation_status_values_are_unique(self):
        """Test that all ValidationStatus values are unique."""
        values = [s.value for s in ValidationStatus]
        assert len(values) == len(set(values))


class TestValidationResult:
    """Tests for ValidationResult dataclass."""
    
    def test_validation_result_creation(self):
        """Test creating a ValidationResult."""
        result = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
            message="All steps completed successfully",
            passed_checks=["Step 1: OK", "Step 2: OK"],
            failed_checks=[],
            warnings=["Minor warning"],
            errors=[],
            metadata={"task_type": "project_analysis"},
        )
        
        assert result.status == ValidationStatus.SUCCESS
        assert result.success is True
        assert result.message == "All steps completed successfully"
        assert len(result.passed_checks) == 2
        assert len(result.failed_checks) == 0
        assert len(result.warnings) == 1
        assert len(result.errors) == 0
        assert result.metadata == {"task_type": "project_analysis"}
    
    def test_validation_result_defaults(self):
        """Test ValidationResult default values."""
        result = ValidationResult()
        
        assert result.status == ValidationStatus.UNDETERMINED
        assert result.success is False
        assert result.message == ""
        assert result.passed_checks == []
        assert result.failed_checks == []
        assert result.warnings == []
        assert result.errors == []
        assert result.successful_results == []
        assert result.failed_results == []
        assert result.metadata == {}
    
    def test_has_errors(self):
        """Test checking for errors."""
        result1 = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
            errors=[],
        )
        assert result1.has_errors() is False
        
        result2 = ValidationResult(
            status=ValidationStatus.FAILURE,
            success=False,
            errors=["Something went wrong"],
        )
        assert result2.has_errors() is True
    
    def test_has_partial_success(self):
        """Test checking for partial success."""
        result1 = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
        )
        assert result1.has_partial_success() is False
        
        result2 = ValidationResult(
            status=ValidationStatus.PARTIAL_SUCCESS,
            success=False,
        )
        assert result2.has_partial_success() is True
        
        result3 = ValidationResult(
            status=ValidationStatus.FAILURE,
            success=False,
        )
        assert result3.has_partial_success() is False
    
    def test_to_summary_success(self):
        """Test generating summary for successful validation."""
        result = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
            message="All steps completed",
            passed_checks=["list_dir: OK", "read_file: OK"],
        )
        
        summary = result.to_summary()
        
        assert "SUCCESS" in summary
        assert "All steps completed" in summary
        assert "list_dir: OK" in summary
        assert "read_file: OK" in summary
    
    def test_to_summary_partial_success(self):
        """Test generating summary for partial success."""
        result = ValidationResult(
            status=ValidationStatus.PARTIAL_SUCCESS,
            success=False,
            message="Some steps succeeded, some failed",
            passed_checks=["list_dir: OK"],
            failed_checks=["read_file: File not found"],
            warnings=["Check file paths"],
        )
        
        summary = result.to_summary()
        
        assert "PARTIAL_SUCCESS" in summary
        assert "list_dir: OK" in summary
        assert "read_file: File not found" in summary
        assert "Check file paths" in summary
    
    def test_to_summary_failure(self):
        """Test generating summary for failure."""
        result = ValidationResult(
            status=ValidationStatus.FAILURE,
            success=False,
            message="All steps failed",
            errors=["Network error", "Permission denied"],
        )
        
        summary = result.to_summary()
        
        assert "FAILURE" in summary
        assert "Network error" in summary
        assert "Permission denied" in summary


class TestResultValidator:
    """Tests for ResultValidator class."""
    
    @pytest.fixture
    def validator(self):
        """Create a ResultValidator instance."""
        return ResultValidator()
    
    def _create_execution_result(
        self,
        step_index: int,
        tool_name: str,
        success: bool,
        output: str = "",
        error_message: str = "",
    ) -> ExecutionResult:
        """Helper to create an ExecutionResult."""
        return ExecutionResult(
            step_index=step_index,
            step_type=StepType.TOOL_CALL,
            tool_name=tool_name,
            status=ExecutionStatus.SUCCESS if success else ExecutionStatus.FAILED,
            success=success,
            output=output,
            error_message=error_message,
        )
    
    @pytest.mark.asyncio
    async def test_validate_all_success(self, validator):
        """Test validating all successful results."""
        results = [
            self._create_execution_result(0, "list_dir", True, output="file1.py\nfile2.py"),
            self._create_execution_result(1, "read_file", True, output="File content"),
        ]
        
        validation = await validator.validate(
            "List and read files",
            results,
            TaskType.FILE_OPERATION,
        )
        
        assert validation.status == ValidationStatus.SUCCESS
        assert validation.success is True
        assert len(validation.passed_checks) == 2
        assert len(validation.failed_checks) == 0
        assert validation.metadata["total_steps"] == 2
        assert validation.metadata["successful_steps"] == 2
        assert validation.metadata["failed_steps"] == 0
    
    @pytest.mark.asyncio
    async def test_validate_partial_success(self, validator):
        """Test validating partial success results."""
        results = [
            self._create_execution_result(0, "list_dir", True, output="file1.py\nfile2.py"),
            self._create_execution_result(1, "read_file", False, error_message="File not found"),
        ]
        
        validation = await validator.validate(
            "List and read files",
            results,
            TaskType.FILE_OPERATION,
        )
        
        assert validation.status == ValidationStatus.PARTIAL_SUCCESS
        assert validation.success is False
        assert len(validation.passed_checks) == 1
        assert len(validation.failed_checks) == 1
        assert validation.metadata["successful_steps"] == 1
        assert validation.metadata["failed_steps"] == 1
    
    @pytest.mark.asyncio
    async def test_validate_all_failure(self, validator):
        """Test validating all failed results."""
        results = [
            self._create_execution_result(0, "list_dir", False, error_message="Permission denied"),
            self._create_execution_result(1, "read_file", False, error_message="File not found"),
        ]
        
        validation = await validator.validate(
            "List and read files",
            results,
            TaskType.FILE_OPERATION,
        )
        
        assert validation.status == ValidationStatus.FAILURE
        assert validation.success is False
        assert len(validation.passed_checks) == 0
        assert len(validation.failed_checks) == 2
        assert validation.metadata["successful_steps"] == 0
        assert validation.metadata["failed_steps"] == 2
    
    @pytest.mark.asyncio
    async def test_validate_empty_results(self, validator):
        """Test validating empty results."""
        validation = await validator.validate(
            "Test",
            [],
            TaskType.GENERAL_ASSISTANCE,
        )
        
        assert validation.status == ValidationStatus.UNDETERMINED
        assert validation.success is False
        assert "No execution results" in validation.message
    
    def test_validate_project_analysis(self, validator):
        """Test validating project analysis results."""
        results = [
            self._create_execution_result(0, "list_dir", True, output="src/\ntests/\nREADME.md"),
            self._create_execution_result(1, "glob", True, output="src/main.py"),
        ]
        
        summary = validator._validate_project_analysis(results)
        
        assert isinstance(summary, str)
        assert len(summary) > 0
    
    def test_validate_file_operation(self, validator):
        """Test validating file operation results."""
        results = [
            self._create_execution_result(0, "read_file", True, output="File content"),
        ]
        
        summary = validator._validate_file_operation(results)
        
        assert isinstance(summary, str)
    
    def test_validate_debugging(self, validator):
        """Test validating debugging results."""
        results = [
            self._create_execution_result(0, "read_file", True, output="Code with bug"),
            self._create_execution_result(1, "edit_file", True, output="Fixed code"),
        ]
        
        summary = validator._validate_debugging(results)
        
        assert isinstance(summary, str)
    
    def test_validate_code_execution(self, validator):
        """Test validating code execution results."""
        results = [
            self._create_execution_result(0, "exec", True, output="Test passed"),
        ]
        
        summary = validator._validate_code_execution(results)
        
        assert isinstance(summary, str)
        assert "executed" in summary.lower() or "command" in summary.lower()
    
    def test_generate_error_summary_success(self, validator):
        """Test generating error summary for success."""
        result = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
            message="All good",
        )
        
        summary = validator.generate_error_summary(result)
        
        assert "successfully" in summary.lower()
    
    def test_generate_error_summary_partial(self, validator):
        """Test generating error summary for partial success."""
        result = ValidationResult(
            status=ValidationStatus.PARTIAL_SUCCESS,
            success=False,
            passed_checks=["Step 1: OK"],
            failed_checks=["Step 2: Failed"],
        )
        
        summary = validator.generate_error_summary(result)
        
        assert "Partial" in summary or "部分" in summary
        assert "Step 1: OK" in summary
        assert "Step 2: Failed" in summary
    
    def test_generate_error_summary_failure(self, validator):
        """Test generating error summary for failure."""
        result = ValidationResult(
            status=ValidationStatus.FAILURE,
            success=False,
            errors=["Network error", "Timeout"],
        )
        
        summary = validator.generate_error_summary(result)
        
        assert "Failed" in summary or "失败" in summary
        assert "Network error" in summary
        assert "Timeout" in summary
