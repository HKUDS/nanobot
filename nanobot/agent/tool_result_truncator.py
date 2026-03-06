"""Smart truncation for tool results based on tool type and content structure."""

import json
import re
from typing import Any


class ToolResultTruncator:
    """
    Smart truncation for tool results.
    
    Different tools need different truncation strategies:
    - read_file: Keep head + tail, omit middle
    - exec: Keep stderr + last N lines of stdout
    - web_fetch: Extract key paragraphs via TF-IDF
    - list_dir: Keep first N entries
    - Default: Simple prefix truncation
    """

    def __init__(self, max_chars: int = 2000):
        """
        Initialize truncator.
        
        Args:
            max_chars: Maximum characters to keep (default: 2000, up from 500)
        """
        self.max_chars = max_chars

    def truncate(self, tool_name: str, result: str) -> str:
        """
        Truncate tool result based on tool type.
        
        Args:
            tool_name: Name of the tool that produced the result
            result: Raw tool result string
            
        Returns:
            Truncated result string
        """
        if len(result) <= self.max_chars:
            return result

        # Route to specialized truncators
        if tool_name == "read_file":
            return self._truncate_read_file(result)
        elif tool_name == "exec":
            return self._truncate_exec(result)
        elif tool_name in ("web_fetch", "web_search", "mcp_fetch_fetch"):
            return self._truncate_web_content(result)
        elif tool_name == "list_dir":
            return self._truncate_list_dir(result)
        else:
            return self._truncate_default(result)

    def _truncate_read_file(self, content: str) -> str:
        """
        Truncate file content: keep head + tail, omit middle.
        
        Strategy: Show first 40% and last 40% of content.
        """
        head_size = int(self.max_chars * 0.4)
        tail_size = int(self.max_chars * 0.4)
        
        lines = content.split("\n")
        total_lines = len(lines)
        
        # Estimate lines to keep
        avg_line_len = len(content) / max(total_lines, 1)
        head_lines = max(1, int(head_size / avg_line_len))
        tail_lines = max(1, int(tail_size / avg_line_len))
        
        if head_lines + tail_lines >= total_lines:
            return self._truncate_default(content)
        
        head = "\n".join(lines[:head_lines])
        tail = "\n".join(lines[-tail_lines:])
        omitted = total_lines - head_lines - tail_lines
        
        return f"{head}\n\n... ({omitted} lines omitted) ...\n\n{tail}"

    def _truncate_exec(self, output: str) -> str:
        """
        Truncate shell command output: keep stderr + last N lines of stdout.
        
        Strategy: Errors are most important, then recent output.
        """
        # Try to detect stderr (usually prefixed with "STDERR:")
        stderr_match = re.search(r"STDERR:\s*\n(.*?)(?:\n\nSTDOUT:|$)", output, re.DOTALL)
        stdout_match = re.search(r"STDOUT:\s*\n(.*?)(?:\n\nSTDERR:|$)", output, re.DOTALL)
        
        stderr = stderr_match.group(1).strip() if stderr_match else ""
        stdout = stdout_match.group(1).strip() if stdout_match else output
        
        # Allocate space: 30% for stderr, 70% for stdout tail
        stderr_budget = int(self.max_chars * 0.3)
        stdout_budget = int(self.max_chars * 0.7)
        
        # Truncate stderr if needed
        if stderr and len(stderr) > stderr_budget:
            stderr = stderr[:stderr_budget] + "\n... (stderr truncated)"
        
        # Keep last N lines of stdout
        stdout_lines = stdout.split("\n")
        if len(stdout) > stdout_budget:
            # Estimate lines to keep
            avg_line_len = len(stdout) / max(len(stdout_lines), 1)
            keep_lines = max(1, int(stdout_budget / avg_line_len))
            omitted = len(stdout_lines) - keep_lines
            stdout = f"... ({omitted} lines omitted) ...\n\n" + "\n".join(stdout_lines[-keep_lines:])
        
        # Combine
        parts = []
        if stderr:
            parts.append(f"STDERR:\n{stderr}")
        if stdout:
            parts.append(f"STDOUT:\n{stdout}")
        
        return "\n\n".join(parts) if parts else output[:self.max_chars]

    def _truncate_web_content(self, content: str) -> str:
        """
        Truncate web content: extract key paragraphs.
        
        Strategy: Keep paragraphs with highest keyword density.
        """
        # Split into paragraphs
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        
        if not paragraphs:
            return self._truncate_default(content)
        
        # Simple heuristic: keep paragraphs with most alphanumeric content
        # (filters out navigation, ads, etc.)
        scored = []
        for para in paragraphs:
            # Score = ratio of alphanumeric chars to total chars
            alnum_count = sum(c.isalnum() for c in para)
            score = alnum_count / max(len(para), 1)
            scored.append((score, para))
        
        # Sort by score (descending)
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Collect top paragraphs until budget exhausted
        result = []
        total_len = 0
        for score, para in scored:
            if total_len + len(para) + 2 > self.max_chars:  # +2 for "\n\n"
                break
            result.append(para)
            total_len += len(para) + 2
        
        if not result:
            return self._truncate_default(content)
        
        omitted = len(paragraphs) - len(result)
        suffix = f"\n\n... ({omitted} paragraphs omitted)" if omitted > 0 else ""
        return "\n\n".join(result) + suffix

    def _truncate_list_dir(self, listing: str) -> str:
        """
        Truncate directory listing: keep first N entries.
        
        Strategy: Show first N files/dirs, indicate total count.
        """
        lines = listing.split("\n")
        
        # Estimate lines to keep
        avg_line_len = len(listing) / max(len(lines), 1)
        keep_lines = max(1, int(self.max_chars / avg_line_len))
        
        if keep_lines >= len(lines):
            return listing
        
        kept = "\n".join(lines[:keep_lines])
        omitted = len(lines) - keep_lines
        return f"{kept}\n\n... ({omitted} more entries)"

    def _truncate_default(self, content: str) -> str:
        """
        Default truncation: simple prefix.
        
        Strategy: Keep first N chars, indicate truncation.
        """
        return content[:self.max_chars] + "\n\n... (truncated)"

    def truncate_json(self, tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
        """
        Truncate JSON tool results.
        
        Args:
            tool_name: Name of the tool
            result: JSON result dict
            
        Returns:
            Truncated JSON dict
        """
        # Serialize to string, truncate, then parse back
        json_str = json.dumps(result, indent=2)
        
        if len(json_str) <= self.max_chars:
            return result
        
        # For JSON, keep structure but truncate arrays/strings
        truncated_str = self._truncate_default(json_str)
        
        # Try to parse truncated JSON (may fail if cut mid-structure)
        try:
            return json.loads(truncated_str.replace("\n\n... (truncated)", ""))
        except json.JSONDecodeError:
            # Fallback: return string representation
            return {"_truncated": truncated_str}
