"""Context Compressor for compressing conversation context.

The Context Compressor reduces the size of conversation history and
tool execution results to stay within token limits while preserving
important information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class CompressedContext:
    """Result of context compression.
    
    Contains the compressed context along with metadata about what was kept.
    """
    
    compressed_messages: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    kept_messages_count: int = 0
    removed_messages_count: int = 0
    compressed_tool_results: Dict[str, str] = field(default_factory=dict)
    important_keywords: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContextCompressor:
    """Compressor for conversation context and tool results.
    
    The Context Compressor helps manage token usage by:
    1. Summarizing long tool results
    2. Keeping only recent conversation messages
    3. Preserving important keywords and context
    """
    
    def __init__(
        self,
        max_messages: int = 20,
        max_tool_result_chars: int = 2000,
    ):
        """Initialize the Context Compressor.
        
        Args:
            max_messages: Maximum number of messages to keep in history.
            max_tool_result_chars: Maximum characters per tool result.
        """
        self.max_messages = max_messages
        self.max_tool_result_chars = max_tool_result_chars
    
    async def compress(
        self,
        conversation_history: List[Dict[str, Any]],
        execution_results: List[Any] = None,
    ) -> CompressedContext:
        """Compress the conversation context.
        
        Args:
            conversation_history: The full conversation history.
            execution_results: Optional tool execution results to compress.
            
        Returns:
            CompressedContext with the compressed context.
        """
        logger.info("Compressing context: {} messages, {} results",
                    len(conversation_history), len(execution_results or []))
        
        compressed = CompressedContext()
        
        history_count = len(conversation_history) if conversation_history else 0
        
        if conversation_history and len(conversation_history) > self.max_messages:
            system_messages = [m for m in conversation_history if m.get("role") == "system"]
            recent_messages = conversation_history[-self.max_messages:]
            
            non_system_recent = [m for m in recent_messages if m.get("role") != "system"]
            compressed.compressed_messages = system_messages + non_system_recent
            
            compressed.kept_messages_count = len(compressed.compressed_messages)
            compressed.removed_messages_count = history_count - compressed.kept_messages_count
            
            compressed.summary = (
                f"Context compressed: kept {compressed.kept_messages_count} messages, "
                f"removed {compressed.removed_messages_count} older messages"
            )
        else:
            compressed.compressed_messages = list(conversation_history) if conversation_history else []
            compressed.kept_messages_count = len(compressed.compressed_messages)
            compressed.summary = "Context within limits, no compression needed"
        
        if execution_results:
            compressed.compressed_tool_results = self._compress_tool_results(execution_results)
        
        logger.info("Context compression complete: kept {} messages", compressed.kept_messages_count)
        
        return compressed
    
    def _compress_tool_results(
        self,
        execution_results: List[Any],
    ) -> Dict[str, str]:
        """Compress individual tool results.
        
        Args:
            execution_results: List of execution results.
            
        Returns:
            Dictionary mapping tool names to compressed results.
        """
        compressed: Dict[str, str] = {}
        
        for i, result in enumerate(execution_results):
            if hasattr(result, 'output') and result.output is not None:
                output_str = str(result.output)
                tool_name = getattr(result, 'tool_name', f"tool_{i}")
                
                if len(output_str) > self.max_tool_result_chars:
                    compressed[tool_name] = self._summarize_long_output(output_str, tool_name)
                else:
                    compressed[tool_name] = output_str
        
        return compressed
    
    def _summarize_long_output(self, output: str, tool_name: str) -> str:
        """Summarize a long tool output.
        
        Args:
            output: The original long output.
            tool_name: Name of the tool that produced the output.
            
        Returns:
            A summarized version of the output.
        """
        lines = output.split('\n')
        
        if len(lines) > 50:
            preview = lines[:20]
            preview.append("...")
            preview.extend(lines[-10:])
            summary = '\n'.join(preview)
        else:
            summary = output
        
        if len(summary) > self.max_tool_result_chars:
            summary = summary[:self.max_tool_result_chars - 50] + "...\n[Output truncated]"
        
        line_count = len(lines)
        char_count = len(output)
        
        return (
            f"[Tool {tool_name} output: {line_count} lines, {char_count} chars]\n"
            f"{summary}\n"
            f"[Full output available in execution history]"
        )
    
    def extract_important_keywords(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[str]:
        """Extract important keywords from messages.
        
        Args:
            messages: List of conversation messages.
            
        Returns:
            List of important keywords.
        """
        keywords: List[str] = []
        
        important_indicators = [
            "error", "bug", "issue", "problem", "fix",
            "file", "directory", "folder", "path",
            "function", "class", "method", "variable",
            "import", "require", "include",
            "test", "debug", "deploy", "build",
        ]
        
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                content_lower = content.lower()
                for indicator in important_indicators:
                    if indicator in content_lower and indicator not in keywords:
                        keywords.append(indicator)
        
        return keywords
    
    def compress_for_next_iteration(
        self,
        messages: List[Dict[str, Any]],
        execution_results: List[Any],
    ) -> List[Dict[str, Any]]:
        """Compress context specifically for the next workflow iteration.
        
        This method creates a message list optimized for the next LLM call,
        keeping important context while managing token usage.
        
        Args:
            messages: Current conversation messages.
            execution_results: Tool execution results from this iteration.
            
        Returns:
            Compressed message list ready for the next iteration.
        """
        compressed = await self.compress(messages, execution_results)
        
        result_messages = list(compressed.compressed_messages)
        
        if compressed.compressed_tool_results:
            summary_parts = []
            for tool_name, result in compressed.compressed_tool_results.items():
                summary_parts.append(f"### Tool: {tool_name}\n{result}")
            
            summary_msg = {
                "role": "system",
                "content": (
                    "--- Execution Results Summary ---\n"
                    + "\n\n".join(summary_parts)
                    + "\n--- End Summary ---"
                ),
            }
            result_messages.append(summary_msg)
        
        return result_messages
