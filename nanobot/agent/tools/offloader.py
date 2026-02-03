"""
Tool Response Offloader

Offloads large tool responses to the file system to reduce context bloat.
Only a preview is loaded into the LLM context, with a reference to the full
content that the agent can access on demand.
"""

import json
import os
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from datetime import datetime, timedelta

from loguru import logger
import tiktoken

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.base import Tool
from nanobot.config.schema import OffloadConfig


# Default artifacts directory within the workspace
DEFAULT_ARTIFACTS_DIR = ".artifacts"


@dataclass
class OffloadedResponse:
    """Represents an offloaded tool response."""

    artifact_id: str
    artifact_path: str
    preview: str
    original_tokens: int
    preview_tokens: int
    tool_name: str
    timestamp: str

    @property
    def context_message(self) -> str:
        """Generate the message to include in LLM context."""
        tokens_saved = self.original_tokens - self.preview_tokens
        return (
            f"[TOOL RESPONSE OFFLOADED]\n"
            f"Tool: {self.tool_name}\n"
            f"Artifact ID: {self.artifact_id}\n"
            f"Original size: {self.original_tokens} tokens → Preview: {self.preview_tokens} tokens "
            f"(saved {tokens_saved} tokens)\n\n"
            f"--- PREVIEW ---\n{self.preview}\n"
            f"--- END PREVIEW ---\n\n"
            f"📁 Full response saved to: {self.artifact_path}\n"
            f"💡 Use read_artifact('{self.artifact_id}') to load full content when needed."
        )


class ToolResponseOffloader:
    """
    Manages offloading of large tool responses to the file system.
    """

    def __init__(self, workspace: Path, config: OffloadConfig | None = None):
        self.workspace = workspace
        self.config = config or OffloadConfig()
        self.storage_path = self.workspace / self.config.storage_dir
        
        # Tools that should NEVER be offloaded to prevent loops
        self.no_offload_tools = {"read_artifact", "tail_artifact", "search_artifact"}
        
        # Initialize tokenizer once
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            logger.warning("Could not load tiktoken, falling back to char estimation")
            self.tokenizer = None

        if self.config.enabled:
            self._ensure_storage_dir()

        self._artifacts: dict[str, OffloadedResponse] = {}
        self._offload_count = 0
        self._tokens_saved = 0

    def _ensure_storage_dir(self):
        """Create storage directory if it doesn't exist."""
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Create .gitignore to avoid committing artifacts
        gitignore_path = self.storage_path / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text("*\n!.gitignore\n")

    def count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken (accurate) or estimation."""
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text))
            except Exception:
                pass
        return len(text) // 4  # Fallback estimation

    def _generate_artifact_id(self, tool_name: str, content: str) -> str:
        """Generate a unique but readable artifact ID."""
        content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = "".join(c if c.isalnum() or c == "_" else "_" for c in tool_name)
        return f"{clean_name}_{timestamp}_{content_hash}"

    def should_offload(self, tool_name: str, response: str) -> bool:
        """Check if a tool response should be offloaded."""
        if not self.config.enabled:
            return False
            
        # LOOP PREVENTION: Never offload artifact reading tools
        if tool_name in self.no_offload_tools:
            return False

        if len(response.encode("utf-8")) > self.config.threshold_bytes:
            return True

        if self.count_tokens(response) > self.config.threshold_tokens:
            return True

        return False

    def get_preview(self, response: str) -> str:
        """Generate a truncated preview of the response."""
        lines = response.split("\n")
        
        # Line-based truncation
        preview_lines = lines[: self.config.max_preview_lines]
        preview = "\n".join(preview_lines)
        
        if self.count_tokens(preview) <= self.config.max_preview_tokens:
            if len(lines) > self.config.max_preview_lines:
                preview += f"\n... [{len(lines) - self.config.max_preview_lines} more lines]"
            return preview

        # Token-based truncation if lines are too long
        target_tokens = self.config.max_preview_tokens
        
        if self.tokenizer:
            tokens = self.tokenizer.encode(preview)
            if len(tokens) > target_tokens:
                preview = self.tokenizer.decode(tokens[:target_tokens])
        else:
             # Fallback char count
             target_chars = target_tokens * 4
             preview = preview[:target_chars]

        preview += "\n... [truncated]"
        return preview

    def offload(
        self,
        tool_name: str,
        response: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> OffloadedResponse:
        """Offload a tool response to the file system."""
        artifact_id = self._generate_artifact_id(tool_name, response)
        
        # Detect simple extension
        extension = ".txt"
        stripped = response.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                json.loads(stripped)
                extension = ".json"
            except: 
                pass
        elif stripped.startswith("<"):
            extension = ".xml"

        filename = f"{artifact_id}{extension}"
        artifact_path = self.storage_path / filename

        original_tokens = self.count_tokens(response)
        preview = self.get_preview(response)
        preview_tokens = self.count_tokens(preview)

        # Write file
        artifact_path.write_text(response, encoding="utf-8")

        # Write metadata
        if self.config.include_metadata:
            meta = {
                "artifact_id": artifact_id,
                "tool_name": tool_name,
                "original_tokens": original_tokens,
                "original_bytes": len(response.encode("utf-8")),
                "timestamp": datetime.now().isoformat(),
                "custom": metadata or {},
            }
            (self.storage_path / f"{artifact_id}.meta.json").write_text(json.dumps(meta, indent=2))

        offloaded = OffloadedResponse(
            artifact_id=artifact_id,
            artifact_path=str(artifact_path),
            preview=preview,
            original_tokens=original_tokens,
            preview_tokens=preview_tokens,
            tool_name=tool_name,
            timestamp=datetime.now().isoformat(),
        )

        self._artifacts[artifact_id] = offloaded
        self._offload_count += 1
        self._tokens_saved += original_tokens - preview_tokens
        
        logger.info(f"Offloaded {tool_name} response to {artifact_id} (saved {offloaded.original_tokens - offloaded.preview_tokens} tokens)")

        return offloaded

    def read_artifact(self, artifact_id: str) -> Optional[str]:
        """Read full content of an offloaded artifact."""
        # Check cache first
        if artifact_id in self._artifacts:
            path = Path(self._artifacts[artifact_id].artifact_path)
            if path.exists():
                return path.read_text(encoding="utf-8")

        # Check disk
        for ext in [".txt", ".json", ".xml"]:
            path = self.storage_path / f"{artifact_id}{ext}"
            if path.exists():
                return path.read_text(encoding="utf-8")

        return None

    def tail_artifact(self, artifact_id: str, lines: int = 50) -> Optional[str]:
        """Read last N lines."""
        content = self.read_artifact(artifact_id)
        if content is None:
            return None
        
        all_lines = content.split("\n")
        if len(all_lines) <= lines:
            return content
            
        return f"... [{len(all_lines) - lines} lines above]\n" + "\n".join(all_lines[-lines:])

    def search_artifact(self, artifact_id: str, query: str) -> Optional[str]:
        """Simple case-insensitive line search."""
        content = self.read_artifact(artifact_id)
        if content is None:
            return None
            
        lines = content.split("\n")
        matches = []
        query_lower = query.lower()
        
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                # Get context: line before and after
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                context = "\n".join(lines[start:end])
                matches.append(f"Line {i+1}:\n{context}")
                
                if len(matches) >= 10:
                    break
        
        if not matches:
            return f"No matches found for '{query}'"
            
        return f"Found {len(matches)} matches (showing first 10):\n\n" + "\n---\n".join(matches)
    
    def list_artifacts(self) -> list[dict]:
        """List artifacts in current session."""
        return [
            {
                "id": a.artifact_id,
                "tool": a.tool_name,
                "tokens_saved": a.original_tokens - a.preview_tokens,
                "timestamp": a.timestamp
            }
            for a in self._artifacts.values()
        ]

    def get_stats(self) -> dict:
        return {
            "offload_count": self._offload_count,
            "tokens_saved": self._tokens_saved,
            "active_artifacts": len(self._artifacts)
        }


    def cleanup(self, retention_days: int | None = None) -> int:
        """
        Delete artifacts older than retention period.
        
        Args:
            retention_days: Override config retention days.
            
        Returns:
            Number of files deleted.
        """
        days = retention_days if retention_days is not None else self.config.retention_days
        if days <= 0:
            return 0
            
        cutoff = datetime.now() - timedelta(days=days)
        deleted_count = 0
        
        # Scan directory
        if not self.storage_path.exists():
            return 0
            
        for path in self.storage_path.iterdir():
            if path.name == ".gitignore":
                continue
                
            try:
                # Check modification time
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
                if mtime < cutoff:
                    path.unlink()
                    deleted_count += 1
                    
                    # Remove from memory cache if present
                    # We have to iterate since cache is keyed by ID, not path
                    # This is a bit inefficient but cache should be small
                    for aid, resp in list(self._artifacts.items()):
                        if Path(resp.artifact_path).name == path.name:
                            del self._artifacts[aid]
                            break
            except Exception as e:
                logger.error(f"Failed to delete {path}: {e}")
                
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old artifacts (older than {days} days)")
            
        return deleted_count


class ReadArtifactTool(Tool):
    """Tool to read the full content of an offloaded tool response."""
    
    def __init__(self, offloader: ToolResponseOffloader):
        self.offloader = offloader
    
    @property
    def name(self) -> str:
        return "read_artifact"
    
    @property
    def description(self) -> str:
        return (
            "Read the full content of an offloaded tool response. "
            "Use this when a tool response was too large and you only got a preview."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "artifact_id": {
                    "type": "string",
                    "description": "The artifact ID shown in the offloaded response message"
                }
            },
            "required": ["artifact_id"]
        }
    
    async def execute(self, artifact_id: str) -> str:
        content = self.offloader.read_artifact(artifact_id)
        if content is None:
            return f"Error: Artifact '{artifact_id}' not found. Check the ID and try again."
        return content


class TailArtifactTool(Tool):
    """Tool to read the last N lines of an artifact."""
    
    def __init__(self, offloader: ToolResponseOffloader):
        self.offloader = offloader
    
    @property
    def name(self) -> str:
        return "tail_artifact"
    
    @property
    def description(self) -> str:
        return "Read the last N lines of an offloaded artifact. Useful for large logs."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "artifact_id": {
                    "type": "string",
                    "description": "The artifact ID to read"
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines from the end (default: 50)",
                    "default": 50
                }
            },
            "required": ["artifact_id"]
        }
    
    async def execute(self, artifact_id: str, lines: int = 50) -> str:
        content = self.offloader.tail_artifact(artifact_id, lines)
        if content is None:
            return f"Error: Artifact '{artifact_id}' not found."
        return content


class SearchArtifactTool(Tool):
    """Tool to search within an artifact."""
    
    def __init__(self, offloader: ToolResponseOffloader):
        self.offloader = offloader
    
    @property
    def name(self) -> str:
        return "search_artifact"
    
    @property
    def description(self) -> str:
        return "Search for text within an offloaded artifact. Returns matching lines with context."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "artifact_id": {
                    "type": "string",
                    "description": "The artifact ID to search"
                },
                "query": {
                    "type": "string",
                    "description": "Search term (case-insensitive)"
                }
            },
            "required": ["artifact_id", "query"]
        }
    
    async def execute(self, artifact_id: str, query: str) -> str:
        content = self.offloader.search_artifact(artifact_id, query)
        if content is None:
            return f"Error: Artifact '{artifact_id}' not found."
        return content


class ListArtifactsTool(Tool):
    """Tool to list all artifacts in the current session."""
    
    def __init__(self, offloader: ToolResponseOffloader):
        self.offloader = offloader
    
    @property
    def name(self) -> str:
        return "list_artifacts"
    
    @property
    def description(self) -> str:
        return "List all tool responses that have been offloaded in the current session."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }
    
    async def execute(self) -> str:
        artifacts = self.offloader.list_artifacts()
        if not artifacts:
            return "No artifacts have been offloaded in this session."
        
        lines = ["Offloaded artifacts in this session:\n"]
        for a in artifacts:
            lines.append(f"• {a['id']}\n  Tool: {a['tool']}, Tokens saved: {a['tokens_saved']}")
            
        stats = self.offloader.get_stats()
        lines.append(f"\nTotal tokens saved: {stats['tokens_saved']}")
        return "\n".join(lines)


class CleanupArtifactsTool(Tool):
    """Tool to clean up old artifacts."""
    
    def __init__(self, offloader: ToolResponseOffloader):
        self.offloader = offloader
    
    @property
    def name(self) -> str:
        return "cleanup_artifacts"
    
    @property
    def description(self) -> str:
        return "Delete offloaded artifacts older than the configured retention period."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "retention_days": {
                    "type": "integer",
                    "description": "Override configured retention days (optional)"
                }
            },
            "required": []
        }
    
    async def execute(self, retention_days: int | None = None) -> str:
        count = self.offloader.cleanup(retention_days)
        return f"Cleanup complete. Deleted {count} files older than {retention_days or self.offloader.config.retention_days} days."
