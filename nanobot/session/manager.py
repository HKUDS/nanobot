"""Session management for conversation history."""

import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir, safe_filename


def estimate_tokens(text: str) -> int:
    """
    Estimate token count from text.
    
    Based on actual API usage data from in.json/out.json:
    - 56,129 chars -> 26,470 tokens (mixed Chinese/English)
    - Chinese (38.6%): ~1.3 chars per token
    - Other (61.4%): ~3.5 chars per token
    - Overall ratio: ~2.12 chars per token
    """
    if not text:
        return 0
    
    # Count Chinese characters (CJK Unified Ideographs)
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # Count other characters
    other_chars = len(text) - chinese_chars
    
    # Optimized weights based on real data:
    # - Chinese: 1.3 chars per token (higher token density)
    # - Other: 3.5 chars per token
    estimated_tokens = (chinese_chars / 1.3) + (other_chars / 3.5)
    
    return int(estimated_tokens)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """
    Estimate total tokens for a list of messages.
    
    Based on actual API usage from in.json/out.json:
    - Full prompt: 56,129 chars -> 26,470 tokens
    - Content: ~26,000 tokens
    - Message overhead: ~3-4 tokens per message (role, formatting)
    """
    total_content = 0
    msg_count = 0
    
    for msg in messages:
        # Content tokens
        content = msg.get("content", "")
        if isinstance(content, str):
            total_content += estimate_tokens(content)
        elif isinstance(content, list):
            # Handle multi-modal content (e.g., images + text)
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    total_content += estimate_tokens(item["text"])
        msg_count += 1
    
    # Add message overhead (~3.5 tokens per message for role, formatting, etc.)
    overhead = msg_count * 3.5
    
    return int(total_content + overhead)


@dataclass
class Session:
    """
    A conversation session.

    Stores messages in JSONL format for easy reading and persistence.

    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files
    
    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()
    
    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Get recent messages in LLM format (role + content only)."""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages[-max_messages:]]
    
    def get_history_for_compression(
        self,
        max_messages: int = 50
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Get message history split into parts for compression.
        
        Returns:
            Tuple of (system_messages, older_messages_to_compress, recent_messages_to_keep).
        """
        # Get recent messages
        recent = self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages
        
        # Convert to LLM format
        messages = [{"role": m["role"], "content": m["content"]} for m in recent]
        
        if len(messages) <= 15:
            # Not enough messages to compress
            return [], messages, []
        
        # Split messages
        system_msgs = []
        start_idx = 0
        
        # Extract system messages from beginning
        while start_idx < len(messages) and messages[start_idx].get("role") == "system":
            system_msgs.append(messages[start_idx])
            start_idx += 1
        
        # Keep last 10 messages, compress the middle
        keep_recent = 10
        recent_msgs = messages[-keep_recent:]
        older_msgs = messages[start_idx:-keep_recent] if len(messages) > keep_recent else []
        
        return system_msgs, older_msgs, recent_msgs
    
    def compress_with_summary(
        self,
        system_msgs: list[dict[str, Any]],
        older_msgs: list[dict[str, Any]],
        recent_msgs: list[dict[str, Any]],
        summary: str
    ) -> list[dict[str, Any]]:
        """
        Reconstruct message list with LLM-generated summary.
        
        Args:
            system_msgs: System messages to keep.
            older_msgs: Older messages that were summarized.
            recent_msgs: Recent messages to keep as-is.
            summary: LLM-generated summary of older messages.
        
        Returns:
            Compressed message list.
        """
        compressed = []
        
        # Add system messages
        compressed.extend(system_msgs)
        
        # Add summary as a user message
        if summary:
            summary_msg = {
                "role": "user",
                "content": f"[Earlier conversation context - the user and I previously discussed: {summary}]"
            }
            compressed.append(summary_msg)
        
        # Add recent messages
        compressed.extend(recent_msgs)
        
        # Calculate token reduction
        original_tokens = estimate_messages_tokens(system_msgs + older_msgs + recent_msgs)
        compressed_tokens = estimate_messages_tokens(compressed)
        logger.info(f"Compressed context from ~{original_tokens} to ~{compressed_tokens} tokens using LLM summary")
        
        return compressed
    
    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(Path.home() / ".nanobot" / "sessions")
        self._cache: dict[str, Session] = {}
    
    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"
    
    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.
        
        Args:
            key: Session key (usually channel:chat_id).
        
        Returns:
            The session.
        """
        # Check if file exists
        path = self._get_session_path(key)
        file_exists = path.exists()
        
        # Check cache
        if key in self._cache:
            # If file was deleted externally but we have cache, invalidate cache
            if not file_exists:
                logger.info(f"Session file deleted externally, clearing cache for {key}")
                self._cache.pop(key, None)
            else:
                return self._cache[key]
        
        session = self._load(key)
        if session is None:
            session = Session(key=key)
        
        self._cache[key] = session
        return session
    
    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
<<<<<<< Updated upstream
            last_consolidated = 0

            with open(path) as f:
=======
            
            with open(path, encoding="utf-8") as f:
>>>>>>> Stashed changes
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
<<<<<<< Updated upstream
                last_consolidated=last_consolidated
=======
>>>>>>> Stashed changes
            )
        except Exception as e:
            logger.warning(f"Failed to load session {key}: {e}")
            return None
    
    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)
<<<<<<< Updated upstream

        with open(path, "w") as f:
=======
        
        with open(path, "w", encoding="utf-8") as f:
            # Write metadata first
>>>>>>> Stashed changes
            metadata_line = {
                "_type": "metadata",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
<<<<<<< Updated upstream
                "last_consolidated": session.last_consolidated
            }
            f.write(json.dumps(metadata_line) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg) + "\n")

        self._cache[session.key] = session
    
    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)
=======
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            
            # Write messages
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        
        self._cache[session.key] = session
    
    def delete(self, key: str) -> bool:
        """
        Delete a session.
        
        Args:
            key: Session key.
        
        Returns:
            True if deleted, False if not found.
        """
        # Always remove from cache (even if file doesn't exist)
        had_cache = key in self._cache
        self._cache.pop(key, None)
        if had_cache:
            logger.debug(f"Removed session from cache: {key}")
        
        # Remove file
        path = self._get_session_path(key)
        if path.exists():
            path.unlink()
            logger.info(f"Deleted session file: {path}")
            return True
        
        # If we had cache but no file, we still "deleted" something
        return had_cache
    
    def clear_cache(self, key: str | None = None) -> None:
        """
        Clear session from cache.
        
        Args:
            key: Specific session key to clear, or None to clear all.
        """
        if key:
            self._cache.pop(key, None)
            logger.debug(f"Cleared session from cache: {key}")
        else:
            self._cache.clear()
            logger.debug("Cleared all sessions from cache")
>>>>>>> Stashed changes
    
    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.
        
        Returns:
            List of session info dicts.
        """
        sessions = []
        
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # Read just the metadata line
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            sessions.append({
                                "key": path.stem.replace("_", ":"),
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path)
                            })
            except Exception:
                continue
        
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
