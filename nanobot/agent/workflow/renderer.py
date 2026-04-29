"""Report Renderer for generating user-friendly reports.

The Report Renderer takes the execution and validation results and
generates a formatted, user-friendly report in Chinese or English
as appropriate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from nanobot.agent.workflow.executor import ExecutionResult
from nanobot.agent.workflow.planner import ExecutionPlan
from nanobot.agent.workflow.router import TaskType
from nanobot.agent.workflow.validator import ValidationResult, ValidationStatus


@dataclass
class RenderedReport:
    """Result of report rendering.
    
    Contains the final report content along with metadata.
    """
    
    content: str
    format: str = "markdown"
    language: str = "auto"
    sections: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ReportRenderer:
    """Renderer for generating user-friendly reports.
    
    The Report Renderer takes all the workflow results and generates
    a comprehensive, formatted report that's easy for users to read.
    It handles:
    - Structuring results into sections
    - Formatting for readability
    - Chinese language support (no garbled text)
    - Clear indication of success/failure/partial success
    """
    
    TASK_TYPE_NAMES: Dict[TaskType, Dict[str, str]] = {
        TaskType.CODE_ANALYSIS: {"en": "Code Analysis", "zh": "代码分析"},
        TaskType.FILE_OPERATION: {"en": "File Operation", "zh": "文件操作"},
        TaskType.SEARCH: {"en": "Search", "zh": "搜索"},
        TaskType.WEB_SEARCH: {"en": "Web Search", "zh": "网页搜索"},
        TaskType.CODE_EXECUTION: {"en": "Code Execution", "zh": "代码执行"},
        TaskType.QUESTION_ANSWERING: {"en": "Question Answering", "zh": "问答"},
        TaskType.PROJECT_ANALYSIS: {"en": "Project Analysis", "zh": "项目分析"},
        TaskType.DEBUGGING: {"en": "Debugging", "zh": "调试"},
        TaskType.REFACTORED: {"en": "Refactoring", "zh": "重构"},
        TaskType.DOCUMENTATION: {"en": "Documentation", "zh": "文档"},
        TaskType.TESTING: {"en": "Testing", "zh": "测试"},
        TaskType.DEPLOYMENT: {"en": "Deployment", "zh": "部署"},
        TaskType.CONFIGURATION: {"en": "Configuration", "zh": "配置"},
        TaskType.GENERAL_ASSISTANCE: {"en": "General Assistance", "zh": "通用协助"},
        TaskType.UNKNOWN: {"en": "Unknown", "zh": "未知"},
    }
    
    STATUS_ICONS: Dict[ValidationStatus, str] = {
        ValidationStatus.SUCCESS: "✅",
        ValidationStatus.PARTIAL_SUCCESS: "⚠️",
        ValidationStatus.FAILURE: "❌",
        ValidationStatus.UNDETERMINED: "❓",
    }
    
    STATUS_NAMES: Dict[ValidationStatus, Dict[str, str]] = {
        ValidationStatus.SUCCESS: {"en": "Success", "zh": "成功"},
        ValidationStatus.PARTIAL_SUCCESS: {"en": "Partial Success", "zh": "部分成功"},
        ValidationStatus.FAILURE: {"en": "Failure", "zh": "失败"},
        ValidationStatus.UNDETERMINED: {"en": "Undetermined", "zh": "未确定"},
    }
    
    def __init__(self, default_language: str = "auto"):
        """Initialize the Report Renderer.
        
        Args:
            default_language: Default language for reports ('auto', 'en', or 'zh').
        """
        self.default_language = default_language
    
    async def render(
        self,
        user_input: str,
        task_type: TaskType,
        plan: Optional[ExecutionPlan] = None,
        execution_results: List[ExecutionResult] = None,
        validation_result: Optional[ValidationResult] = None,
    ) -> RenderedReport:
        """Render a comprehensive report from workflow results.
        
        Args:
            user_input: The original user request.
            task_type: The identified task type.
            plan: Optional execution plan.
            execution_results: Optional list of execution results.
            validation_result: Optional validation result.
            
        Returns:
            RenderedReport with the formatted report.
        """
        logger.info("Rendering report for task type: {}", task_type.value)
        
        language = self._detect_language(user_input)
        
        sections: List[Dict[str, str]] = []
        report_parts: List[str] = []
        
        status = validation_result.status if validation_result else ValidationStatus.UNDETERMINED
        status_icon = self.STATUS_ICONS.get(status, "❓")
        status_name = self.STATUS_NAMES.get(status, {}).get(language, status.value)
        task_name = self.TASK_TYPE_NAMES.get(task_type, {}).get(language, task_type.value)
        
        title = f"{status_icon} {task_name} - {status_name}"
        report_parts.append(f"# {title}")
        report_parts.append("")
        
        sections.append({"title": "Status", "content": title})
        
        if validation_result:
            summary_section = self._render_validation_summary(validation_result, language)
            report_parts.append(summary_section)
            sections.append({"title": "Summary", "content": summary_section})
        
        if execution_results:
            execution_section = self._render_execution_results(execution_results, language)
            report_parts.append(execution_section)
            sections.append({"title": "Execution Results", "content": execution_section})
        
        if validation_result and validation_result.has_errors():
            error_section = self._render_error_details(validation_result, language)
            report_parts.append(error_section)
            sections.append({"title": "Error Details", "content": error_section})
        
        if validation_result and validation_result.warnings:
            warning_section = self._render_warnings(validation_result, language)
            report_parts.append(warning_section)
            sections.append({"title": "Warnings", "content": warning_section})
        
        footer = self._render_footer(language)
        report_parts.append(footer)
        sections.append({"title": "Footer", "content": footer})
        
        final_content = "\n\n".join(report_parts)
        
        final_content = self._ensure_utf8_encoding(final_content)
        
        logger.info("Report rendered: {} sections, {} characters",
                    len(sections), len(final_content))
        
        return RenderedReport(
            content=final_content,
            format="markdown",
            language=language,
            sections=sections,
            metadata={
                "task_type": task_type.value,
                "status": status.value,
                "section_count": len(sections),
            },
        )
    
    def _detect_language(self, text: str) -> str:
        """Detect if text is primarily Chinese or English.
        
        Args:
            text: The text to analyze.
            
        Returns:
            'zh' if primarily Chinese, 'en' otherwise.
        """
        if self.default_language != "auto":
            return self.default_language
        
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        total_chars = len(text)
        
        if total_chars > 0 and chinese_chars / total_chars > 0.2:
            return "zh"
        
        return "en"
    
    def _render_validation_summary(
        self,
        result: ValidationResult,
        language: str,
    ) -> str:
        """Render the validation summary section.
        
        Args:
            result: The validation result.
            language: The target language.
            
        Returns:
            Formatted summary string.
        """
        lines: List[str] = []
        
        if language == "zh":
            lines.append("## 执行摘要")
            lines.append("")
            lines.append(f"**状态**: {self.STATUS_ICONS.get(result.status, '❓')} {self.STATUS_NAMES.get(result.status, {}).get('zh', result.status.value)}")
            lines.append("")
            
            if result.message:
                lines.append(result.message)
                lines.append("")
            
            lines.append(f"- ✅ 成功步骤: {len(result.passed_checks)}")
            lines.append(f"- ❌ 失败步骤: {len(result.failed_checks)}")
            lines.append(f"- ⚠️ 警告: {len(result.warnings)}")
            lines.append(f"- 💥 错误: {len(result.errors)}")
        else:
            lines.append("## Execution Summary")
            lines.append("")
            lines.append(f"**Status**: {self.STATUS_ICONS.get(result.status, '❓')} {self.STATUS_NAMES.get(result.status, {}).get('en', result.status.value)}")
            lines.append("")
            
            if result.message:
                lines.append(result.message)
                lines.append("")
            
            lines.append(f"- ✅ Successful steps: {len(result.passed_checks)}")
            lines.append(f"- ❌ Failed steps: {len(result.failed_checks)}")
            lines.append(f"- ⚠️ Warnings: {len(result.warnings)}")
            lines.append(f"- 💥 Errors: {len(result.errors)}")
        
        return "\n".join(lines)
    
    def _render_execution_results(
        self,
        results: List[ExecutionResult],
        language: str,
    ) -> str:
        """Render the execution results section.
        
        Args:
            results: List of execution results.
            language: The target language.
            
        Returns:
            Formatted execution results string.
        """
        lines: List[str] = []
        
        if language == "zh":
            lines.append("## 执行详情")
        else:
            lines.append("## Execution Details")
        
        lines.append("")
        
        for i, result in enumerate(results):
            status_icon = "✅" if result.success else "❌"
            tool_name = result.tool_name or f"Step {i}"
            
            lines.append(f"### {status_icon} {tool_name}")
            lines.append("")
            
            if result.success:
                if result.output is not None:
                    output_str = str(result.output)
                    if len(output_str) > 500:
                        output_str = output_str[:500] + "\n... (output truncated)"
                    lines.append("**Output**:")
                    lines.append("```")
                    lines.append(output_str)
                    lines.append("```")
                else:
                    if language == "zh":
                        lines.append("*无输出*")
                    else:
                        lines.append("*No output*")
            else:
                error_msg = result.error_message or "Unknown error"
                lines.append(f"**Error**: {error_msg}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def _render_error_details(
        self,
        result: ValidationResult,
        language: str,
    ) -> str:
        """Render the error details section.
        
        Args:
            result: The validation result.
            language: The target language.
            
        Returns:
            Formatted error details string.
        """
        lines: List[str] = []
        
        if language == "zh":
            lines.append("## 错误详情")
            lines.append("")
            lines.append("以下是遇到的错误：")
        else:
            lines.append("## Error Details")
            lines.append("")
            lines.append("The following errors were encountered:")
        
        lines.append("")
        
        for i, error in enumerate(result.errors, 1):
            lines.append(f"{i}. {error}")
        
        if result.failed_checks:
            lines.append("")
            if language == "zh":
                lines.append("**失败的检查项**:")
            else:
                lines.append("**Failed checks**:")
            lines.append("")
            for check in result.failed_checks:
                lines.append(f"- ❌ {check}")
        
        return "\n".join(lines)
    
    def _render_warnings(
        self,
        result: ValidationResult,
        language: str,
    ) -> str:
        """Render the warnings section.
        
        Args:
            result: The validation result.
            language: The target language.
            
        Returns:
            Formatted warnings string.
        """
        lines: List[str] = []
        
        if language == "zh":
            lines.append("## ⚠️ 警告")
            lines.append("")
            lines.append("请注意以下警告：")
        else:
            lines.append("## ⚠️ Warnings")
            lines.append("")
            lines.append("Please note the following warnings:")
        
        lines.append("")
        
        for warning in result.warnings:
            lines.append(f"- {warning}")
        
        return "\n".join(lines)
    
    def _render_footer(self, language: str) -> str:
        """Render the report footer.
        
        Args:
            language: The target language.
            
        Returns:
            Formatted footer string.
        """
        lines: List[str] = []
        
        lines.append("---")
        lines.append("")
        
        if language == "zh":
            lines.append("*此报告由 Nanobot Agent Workflow 生成*")
            lines.append("")
            lines.append("💡 提示:")
            lines.append("- 如果任务部分成功，可以提供更多信息来重试失败的步骤")
            lines.append("- 如果遇到错误，请检查错误详情并尝试不同的方法")
            lines.append("- 您可以要求更详细的执行记录来了解具体发生了什么")
        else:
            lines.append("*This report was generated by Nanobot Agent Workflow*")
            lines.append("")
            lines.append("💡 Tips:")
            lines.append("- If the task partially succeeded, you can retry failed steps with more information")
            lines.append("- If you encountered errors, check the error details and try a different approach")
            lines.append("- You can ask for more detailed execution logs to understand what happened")
        
        return "\n".join(lines)
    
    def _ensure_utf8_encoding(self, text: str) -> str:
        """Ensure text is properly encoded for UTF-8.
        
        This helps prevent garbled Chinese text.
        
        Args:
            text: The text to process.
            
        Returns:
            Text with proper UTF-8 handling.
        """
        try:
            text.encode('utf-8').decode('utf-8')
            return text
        except UnicodeEncodeError:
            pass
        
        try:
            return text.encode('utf-8', errors='replace').decode('utf-8')
        except Exception:
            return text
    
    def render_simple_error(
        self,
        error_message: str,
        language: str = "en",
    ) -> str:
        """Render a simple error message.
        
        Args:
            error_message: The error message to display.
            language: The target language.
            
        Returns:
            Formatted error message.
        """
        if language == "zh":
            return (
                "## ❌ 错误\n\n"
                f"{error_message}\n\n"
                "---\n\n"
                "*工作流执行失败*"
            )
        else:
            return (
                "## ❌ Error\n\n"
                f"{error_message}\n\n"
                "---\n\n"
                "*Workflow execution failed*"
            )
