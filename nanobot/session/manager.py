"""Session management for conversation history."""

import asyncio
import json
import json_repair
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.utils.helpers import ensure_dir, safe_filename

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


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
        # Map user_key (channel:chat_id) to current session_id
        self.session_table: dict[str, str] = {}  
        self.session_table_path = self.sessions_dir / "session_table.json"
        self._load_session_table()
    def _load_session_table(self) -> None:
        """Load session_table from disk."""
        if self.session_table_path.exists():
            try:
                with open(self.session_table_path) as f:
                    self.session_table = json.load(f)
                logger.info(f"Loaded session table with {len(self.session_table)} entries")
            except Exception as e:
                logger.warning(f"Failed to load session table: {e}")
                self.session_table = {}
        else:
            self.session_table = {}
    
    def _save_session_table(self) -> None:
        """Save session_table to disk."""
        try:
            with open(self.session_table_path, "w") as f:
                json.dump(self.session_table, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save session table: {e}")
    
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
        # Create user_key
        # user_key = f"{channel}:{chat_id}"
        
        # Check if user has a current session
        session_id = self.session_table.get(key)
        
        if session_id:
            # Check cache first
            if session_id in self._cache:
                return self._cache[session_id]
            
            session = self._load(session_id)
            if session:
                self._cache[session_id] = session
                return session
            else:
                # Session file missing, create new one
                logger.warning(f"Session {session_id} not found, creating new one")
        
        # Create new session
        return self.create_new_session(key)

    
    def _load(self, key: str) -> Session | None:
        """Load a session from disk by session_id."""
        path = self._get_session_path(key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            last_consolidated = 0

            with open(path) as f:
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
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning(f"Failed to load session {key}: {e}")
            return None
    
    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)

        with open(path, "w") as f:
            metadata_line = {
                "_type": "metadata",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated
            }
            f.write(json.dumps(metadata_line) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg) + "\n")

        self._cache[session.key] = session
    
    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.
        
        Returns:
            List of session info dicts.
        """
        sessions = []
        
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                session_id = path.stem.replace("_", ":")
                session = self._cache.get(session_id) or self._load(session_id)
                # Read just the metadata line
                with open(path) as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            sessions.append({
                                "key": path.stem.replace("_", ":"),
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "message_count": len(session.messages) if session else 0,
                                "path": str(path)
                            })
            except Exception:
                continue
        
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
    
    async def consolidate_memory(
        self, 
        session: "Session", 
        provider: "LLMProvider",
        model: str,
        archive_all: bool = False,
        memory_window: int = 50
    ) -> None:
        """Consolidate old messages into MEMORY.md + HISTORY.md.
        
        Args:
            session: The session to consolidate.
            provider: LLM provider for consolidation analysis.
            model: Model name to use for consolidation.
            archive_all: If True, archive all messages. If False, only archive old ones.
            memory_window: Window size for keeping recent messages.
        """
        from nanobot.agent.memory import MemoryStore
        
        memory = MemoryStore(self.workspace)

        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info(f"Memory consolidation (archive_all): {len(session.messages)} total messages archived")
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                logger.debug(f"Session {session.key}: No consolidation needed (messages={len(session.messages)}, keep={keep_count})")
                return [False, f"Session {session.key}: No consolidation needed (messages={len(session.messages)}, keep={keep_count})"]

            messages_to_process = len(session.messages) - session.last_consolidated
            if messages_to_process <= 0:
                logger.debug(f"Session {session.key}: No new messages to consolidate (last_consolidated={session.last_consolidated}, total={len(session.messages)})")
                return [False, f"Session {session.key}: No new messages to consolidate (last_consolidated={session.last_consolidated}, total={len(session.messages)})"]

            old_messages = session.messages[session.last_consolidated:-keep_count]
            if not old_messages:
                return [False, f"Session {session.key}: No messages to consolidate after applying keep window (keep={keep_count})"]
            logger.info(f"Memory consolidation started: {len(session.messages)} total, {len(old_messages)} new to consolidate, {keep_count} keep")

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")
        conversation = "\n".join(lines)
        current_memory = memory.read_long_term()

        prompt = f"""You are a memory consolidation agent. Process this conversation and return a JSON object with exactly two keys:

1. "history_entry": A paragraph (2-5 sentences) summarizing the key events/decisions/topics. Start with a timestamp like [YYYY-MM-DD HH:MM]. Include enough detail to be useful when found by grep search later.

2. "memory_update": The updated long-term memory content. Add any new facts: user location, preferences, personal info, habits, project context, technical decisions, tools/services used. If nothing new, return the existing content unchanged.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{conversation}

Respond with ONLY valid JSON, no markdown fences."""

        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": "You are a memory consolidation agent. Respond only with valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                model=model,
            )
            text = (response.content or "").strip()
            if not text:
                logger.warning("Memory consolidation: LLM returned empty response, skipping")
                return [False, "Error: LLM returned empty response"]
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json_repair.loads(text)
            if not isinstance(result, dict):
                logger.warning(f"Memory consolidation: unexpected response type, skipping. Response: {text[:200]}")
                return [False, "Error: unexpected response type, skipping"]

            if entry := result.get("history_entry"):
                memory.append_history(entry)
            if update := result.get("memory_update"):
                if update != current_memory:
                    memory.write_long_term(update)

            if archive_all:
                session.last_consolidated = 0
            else:
                session.last_consolidated = len(session.messages) - keep_count
            logger.info(f"Memory consolidation done: {len(session.messages)} messages, last_consolidated={session.last_consolidated}")
            session.messages = session.messages[-keep_count:] 
            return [True, f"Memory consolidation done: {len(session.messages)} messages, last_consolidated={session.last_consolidated}"]

        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")
            return [False, f"Error during memory consolidation: {e}"]
    def create_new_session(self,user_key: str) -> Session:
        # Create new session
        import uuid
        session_id = uuid.uuid4().hex[:12]
        session = Session(key=session_id)
        # Update mapping
        old_session_id = self.session_table.get(user_key)
        self.session_table[user_key] = session_id
        self._save_session_table()
        
        # Cache it
        self._cache[session_id] = session
        self.save(session)
        
        logger.info(f"Created new session {session_id} for {user_key} (previous: {old_session_id})")
        return session

    
    def get_session_info(self, user_key) -> dict[str, Any]:
        """
        Returns:
            Dict with session info.
        """
        session = self.get_or_create(user_key)
        return {
            "session_id": session.key,
            "user_key": user_key,
            "message_count": len(session.messages),
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }
    
    
    def switch_session(self, user_key, session_id: str) -> bool:
        """
        Switch user to a specific session.
        Returns:
            True if successful, False if session not found
        """
       
        
        # Check if session exists
        session = self._load(session_id)
        if not session:
            logger.warning(f"Cannot switch to non-existent session {session_id}")
            return False
            # raise ValueError(f"Session {session_id} not found")
        
        # Update mapping
        old_session_id = self.session_table.get(user_key)
        self.session_table[user_key] = session_id
        self._save_session_table()
        
        logger.info(f"Switched {user_key} from {old_session_id} to {session_id}")
        return True
    
    def delete(self, key: str) -> bool:
        """
        Delete a session.
        
        Args:
            key: Session key.
        
        Returns:
            True if deleted, False if not found.
        """
        # Remove from cache
        self._cache.pop(key, None)
        # Remove file
        path = self._get_session_path(key)
        if path.exists():
            path.unlink()
            return True
        return False