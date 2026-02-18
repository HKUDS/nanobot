"""
A tool for managing a persistent scratchpad of thoughts, hypotheses, and temporary notes.
This acts as a non-authoritative reasoning store, inspired by Tiferet-Assistant's reasoning.py.
"""
import json

from pathlib import Path
from typing import Any
from datetime import datetime, timedelta

from nanobot.agent.tools.base import Tool

REASONING_LOG_FILE = "reasoning.log.md"


class ReasoningTool(Tool):
    """
    Manages a persistent scratchpad for thoughts and hypotheses.
    Actions: add, read, search, clear.
    """

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._log_path = self._workspace / REASONING_LOG_FILE

    @property
    def name(self) -> str:
        return "reasoning_store"

    @property
    def description(self) -> str:
        return "Manage a persistent scratchpad for temporary thoughts. Actions: add, read, search, clear."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "read", "search", "clear"],
                    "description": "Action to perform on the reasoning store.",
                },
                "content": {
                    "type": "string",
                    "description": "The thought or note to add (for 'add' action).",
                },
                "ttl_seconds": {
                    "type": "integer",
                    "description": "Optional Time-To-Live in seconds. The thought will be ignored after this duration.",
                },
                "query": {
                    "type": "string",
                    "description": "A term to search for in the log (for 'search' action).",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self, action: str, content: str = None, query: str = None, ttl_seconds: int = None, **kwargs: Any
    ) -> str:
        try:
            if action == "add":
                if not content:
                    return "Error: 'content' is required for the 'add' action."
                now = datetime.now()
                entry = {
                    "timestamp": now.isoformat(),
                    "content": content,
                }
                if ttl_seconds:
                    entry["expires_at"] = (now + timedelta(seconds=ttl_seconds)).isoformat()

                entry_line = json.dumps(entry) + "\n"
                current_content = ""
                if self._log_path.exists():
                    current_content = self._log_path.read_text(encoding="utf-8")
                self._log_path.write_text(current_content + entry_line, encoding="utf-8")
                return f"Thought added to {REASONING_LOG_FILE}."

            elif action == "read":
                return self._read_and_filter_log()

            elif action == "search":
                if not query:
                    return "Error: 'query' is required for the 'search' action."
                
                log_content = self._read_and_filter_log()
                if "is empty" in log_content:
                    return "Reasoning log is empty or all entries have expired."

                results = [line for line in log_content.splitlines() if query.lower() in line.lower()]
                if not results:
                    return f"No thoughts found matching '{query}'."
                return "Found matching thoughts:\n" + "\n".join(results)

            elif action == "clear":
                if self._log_path.exists():
                    self._log_path.unlink()
                return f"Reasoning log ({REASONING_LOG_FILE}) cleared."
            else:
                return f"Error: Unknown action '{action}'."
        except Exception as e:
            return f"Error executing reasoning tool: {e}"

    def _read_and_filter_log(self) -> str:
        if not self._log_path.exists():
            return "Reasoning log is empty."
        
        now = datetime.now()
        valid_lines = []
        for line in self._log_path.read_text(encoding="utf-8").splitlines():
            if not line: continue
            entry = json.loads(line)
            if "expires_at" in entry and now > datetime.fromisoformat(entry["expires_at"]):
                continue
            valid_lines.append(f"[{entry['timestamp']}] {entry['content']}")
        
        return "\n".join(valid_lines) if valid_lines else "Reasoning log is empty or all entries have expired."