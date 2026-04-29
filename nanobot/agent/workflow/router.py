"""Task Router for identifying user intent and task type.

The Task Router analyzes user input to determine what type of task is being
requested, which helps the Plan Builder create an appropriate execution plan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger


class TaskType(Enum):
    """Enumeration of recognized task types."""
    
    CODE_ANALYSIS = "code_analysis"
    FILE_OPERATION = "file_operation"
    SEARCH = "search"
    WEB_SEARCH = "web_search"
    CODE_EXECUTION = "code_execution"
    QUESTION_ANSWERING = "question_answering"
    PROJECT_ANALYSIS = "project_analysis"
    DEBUGGING = "debugging"
    REFACTORED = "refactoring"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    DEPLOYMENT = "deployment"
    CONFIGURATION = "configuration"
    GENERAL_ASSISTANCE = "general_assistance"
    UNKNOWN = "unknown"


@dataclass
class RoutingResult:
    """Result of task routing.
    
    Contains the identified task type and confidence score.
    """
    
    task_type: TaskType
    confidence: float
    keywords: List[str] = field(default_factory=list)
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


TASK_KEYWORDS: Dict[TaskType, List[str]] = {
    TaskType.CODE_ANALYSIS: [
        "analyze", "analysis", "review", "code review", "examine", "inspect",
        "understand", "explain", "what does", "how does", "explain this",
        "analyze code", "review code", "look at this code", "understand code",
    ],
    TaskType.FILE_OPERATION: [
        "read", "write", "edit", "create", "delete", "move", "copy", "rename",
        "file", "directory", "folder", "list files", "show files", "ls",
        "read file", "write file", "edit file", "create file",
    ],
    TaskType.SEARCH: [
        "search", "find", "grep", "glob", "look for", "find all", "search for",
        "where is", "find file", "search code",
    ],
    TaskType.WEB_SEARCH: [
        "web search", "search web", "google", "search the web", "internet",
        "online", "website", "webpage", "fetch", "get page",
    ],
    TaskType.CODE_EXECUTION: [
        "run", "execute", "exec", "shell", "command", "terminal", "cmd",
        "run this", "execute this", "run command", "run script",
    ],
    TaskType.QUESTION_ANSWERING: [
        "what", "how", "why", "when", "where", "who", "?",
        "can you", "could you", "please tell", "i want to know",
    ],
    TaskType.PROJECT_ANALYSIS: [
        "project", "structure", "architecture", "overview", "summary",
        "analyze project", "project structure", "codebase", "repository",
        "repo", "understand project", "project overview", "tell me about this project",
        "what is this", "what does this project", "project analysis",
    ],
    TaskType.DEBUGGING: [
        "debug", "bug", "error", "fix", "issue", "problem", "not working",
        "why isn't", "why doesn't", "debugging", "troubleshoot",
    ],
    TaskType.REFACTORED: [
        "refactor", "improve", "optimize", "clean up", "rewrite", "simplify",
        "better", "improve code", "clean code",
    ],
    TaskType.DOCUMENTATION: [
        "document", "documentation", "doc", "comments", "comment", "explain",
        "write docs", "add comments", "document this",
    ],
    TaskType.TESTING: [
        "test", "testing", "unit test", "integration test", "write test",
        "create test", "run test", "test this",
    ],
    TaskType.DEPLOYMENT: [
        "deploy", "deployment", "publish", "release", "build", "deploy to",
        "push to", "production", "staging",
    ],
    TaskType.CONFIGURATION: [
        "config", "configuration", "setup", "settings", "environment",
        "configure", "set up", "change config",
    ],
    TaskType.GENERAL_ASSISTANCE: [
        "help", "assist", "can you help", "need help", "assistance",
        "support", "guide me",
    ],
}


class TaskRouter:
    """Router for identifying task type from user input.
    
    The Task Router uses a combination of keyword matching and optional
    LLM-based classification to determine the type of task being requested.
    """
    
    def __init__(self, llm_provider: Any = None, context_builder: Any = None):
        """Initialize the Task Router.
        
        Args:
            llm_provider: Optional LLM provider for advanced classification.
            context_builder: Optional ContextBuilder for accessing workspace context and skills.
        """
        self.llm_provider = llm_provider
        self.context_builder = context_builder
        self._keyword_patterns = self._compile_patterns()
    
    def _compile_patterns(self) -> Dict[TaskType, List[re.Pattern]]:
        """Compile regex patterns for keyword matching.
        
        Returns:
            Dictionary mapping TaskType to list of compiled regex patterns.
        """
        patterns: Dict[TaskType, List[re.Pattern]] = {}
        for task_type, keywords in TASK_KEYWORDS.items():
            patterns[task_type] = [
                re.compile(r'\b' + re.escape(kw.lower()) + r'\b', re.IGNORECASE)
                for kw in keywords
            ]
        return patterns
    
    async def route(
        self,
        user_input: str,
        conversation_history: List[Dict[str, Any]] = None,
    ) -> TaskType:
        """Route the user input to determine the task type.
        
        Args:
            user_input: The user's input message.
            conversation_history: Optional conversation history for context.
            
        Returns:
            The identified TaskType.
        """
        result = await self._route_with_detail(user_input, conversation_history)
        return result.task_type
    
    async def _route_with_detail(
        self,
        user_input: str,
        conversation_history: List[Dict[str, Any]] = None,
    ) -> RoutingResult:
        """Route the user input with detailed result.
        
        Args:
            user_input: The user's input message.
            conversation_history: Optional conversation history for context.
            
        Returns:
            RoutingResult with task type, confidence, and metadata.
        """
        input_lower = user_input.lower()
        
        scores: Dict[TaskType, float] = {}
        matched_keywords: Dict[TaskType, List[str]] = {}
        
        for task_type, patterns in self._keyword_patterns.items():
            score = 0.0
            matched = []
            for i, pattern in enumerate(patterns):
                if pattern.search(input_lower):
                    score += 1.0
                    keyword = TASK_KEYWORDS[task_type][i]
                    matched.append(keyword)
            
            if score > 0:
                scores[task_type] = score
                matched_keywords[task_type] = matched
        
        if user_input.strip().endswith("?"):
            scores[TaskType.QUESTION_ANSWERING] = scores.get(TaskType.QUESTION_ANSWERING, 0) + 0.5
        
        if not scores:
            return RoutingResult(
                task_type=TaskType.UNKNOWN,
                confidence=0.0,
                reasoning="No keywords matched",
            )
        
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_task, best_score = sorted_scores[0]
        
        if len(sorted_scores) > 1:
            second_score = sorted_scores[1][1]
            if best_score < second_score * 1.5:
                best_task = self._disambiguate(user_input, sorted_scores[:3])
        
        total_score = sum(scores.values())
        confidence = best_score / total_score if total_score > 0 else 0.0
        
        return RoutingResult(
            task_type=best_task,
            confidence=confidence,
            keywords=matched_keywords.get(best_task, []),
            reasoning=f"Matched keywords: {', '.join(matched_keywords.get(best_task, []))}",
            metadata={"all_scores": {k.value: v for k, v in scores.items()}},
        )
    
    def _disambiguate(
        self,
        user_input: str,
        candidates: List[Tuple[TaskType, float]],
    ) -> TaskType:
        """Disambiguate between multiple task types with similar scores.
        
        Uses heuristic rules to choose the most appropriate task type.
        
        Args:
            user_input: The user's input.
            candidates: List of (task_type, score) tuples.
            
        Returns:
            The most appropriate TaskType.
        """
        input_lower = user_input.lower()
        
        task_priority = {
            TaskType.WEB_SEARCH: 10,
            TaskType.PROJECT_ANALYSIS: 9,
            TaskType.CODE_EXECUTION: 8,
            TaskType.DEBUGGING: 7,
            TaskType.REFACTORED: 6,
            TaskType.TESTING: 5,
            TaskType.CODE_ANALYSIS: 4,
            TaskType.FILE_OPERATION: 3,
            TaskType.SEARCH: 2,
            TaskType.QUESTION_ANSWERING: 1,
            TaskType.GENERAL_ASSISTANCE: 0,
        }
        
        prioritized = sorted(
            candidates,
            key=lambda x: (task_priority.get(x[0], 0), x[1]),
            reverse=True,
        )
        
        if "web" in input_lower or "internet" in input_lower or "online" in input_lower:
            for task_type, _ in prioritized:
                if task_type == TaskType.WEB_SEARCH:
                    return task_type
        
        if "project" in input_lower or "repository" in input_lower or "repo" in input_lower:
            for task_type, _ in prioritized:
                if task_type == TaskType.PROJECT_ANALYSIS:
                    return task_type
        
        return prioritized[0][0]
    
    def is_project_analysis_request(self, user_input: str) -> bool:
        """Check if the input is a project analysis request.
        
        This is a convenience method for quickly identifying project analysis
        requests without full routing. It can use context_builder to access
        workspace context and skills for more accurate identification.
        
        Args:
            user_input: The user's input message.
            
        Returns:
            True if this appears to be a project analysis request.
        """
        project_keywords = [
            "project", "codebase", "repository", "repo", "architecture",
            "structure", "overview", "tell me about", "what is this",
            "understand this", "analyze this",
        ]
        
        input_lower = user_input.lower()
        
        has_project_keyword = any(
            kw.lower() in input_lower
            for kw in project_keywords
        )
        
        if self.context_builder:
            try:
                workspace = getattr(self.context_builder, 'workspace', None)
                if workspace:
                    common_project_files = [
                        "pyproject.toml", "package.json", "Cargo.toml",
                        "README.md", "README", "setup.py", "go.mod",
                        "Gemfile", "composer.json", "requirements.txt",
                    ]
                    from pathlib import Path
                    if isinstance(workspace, Path):
                        for filename in common_project_files:
                            if (workspace / filename).exists():
                                if "what" in input_lower or "tell" in input_lower or "analyze" in input_lower:
                                    has_project_keyword = True
                                    break
            except Exception as e:
                logger.debug("Error checking workspace for project files: {}", e)
        
        if not has_project_keyword:
            return False
        
        not_project_keywords = [
            "write", "edit", "create", "delete", "run", "execute", "debug",
        ]
        
        has_action_keyword = any(
            kw.lower() in input_lower
            for kw in not_project_keywords
        )
        
        return not has_action_keyword
