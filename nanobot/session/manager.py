"""Session management for conversation history."""

import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir, safe_filename

try:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from nanobot.providers.base import LLMProvider
except ImportError:
    pass


@dataclass
class SessionConfig:
    """
    Per-session configuration.
    
    Each session can have its own model, temperature, and other settings.
    """
    model: str | None = None  # None means use agent default
    temperature: float | None = None
    max_iterations: int | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionConfig":
        """Create from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Session:
    """
    A conversation session.
    
    Stores messages in JSONL format for easy reading and persistence.
    Each session has its own configuration (model, temperature, etc.).
    """
    
    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    config: SessionConfig = field(default_factory=SessionConfig)
    granted_permissions: dict[str, Any] = field(default_factory=lambda: {
        'persistent': set(),  # Permissions granted for all commands
        'one_time': {}  # Permissions granted for specific commands (cmd_hash -> set of permissions)
    })
    pending_permissions: dict[str, Any] = field(default_factory=dict)  # request_id -> PermissionRequest
    
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
    
    def get_history(self, max_messages: int = 50) -> list[dict[str, Any]]:
        """
        Get message history for LLM context.
        
        Args:
            max_messages: Maximum messages to return.
        
        Returns:
            List of messages in LLM format.
        """
        # Get recent messages
        recent = self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages
        
        # Convert to LLM format (just role and content)
        return [{"role": m["role"], "content": m["content"]} for m in recent]
    
    def clear(self) -> None:
        """Clear all messages in the session."""
        self.messages = []
        self.updated_at = datetime.now()
    
    def grant_permission(self, permissions: set[str], mode: str = 'persistent', cmd_hash: str | None = None) -> None:
        """
        Grant permissions for command execution.
        
        Args:
            permissions: Set of permission names to grant.
            mode: 'persistent' for all commands, 'one_time' for specific command.
            cmd_hash: Command hash (required for one_time mode).
        """
        if mode == 'persistent':
            self.granted_permissions['persistent'].update(permissions)
        elif mode == 'one_time':
            if not cmd_hash:
                raise ValueError("cmd_hash required for one_time permission")
            if cmd_hash not in self.granted_permissions['one_time']:
                self.granted_permissions['one_time'][cmd_hash] = set()
            self.granted_permissions['one_time'][cmd_hash].update(permissions)
        self.updated_at = datetime.now()
    
    def revoke_permission(self, permissions: set[str], mode: str = 'persistent') -> None:
        """
        Revoke previously granted permissions.
        
        Args:
            permissions: Set of permission names to revoke.
            mode: 'persistent' or 'all' (clears all one_time permissions too).
        """
        if mode == 'persistent' or mode == 'all':
            self.granted_permissions['persistent'] -= permissions
        if mode == 'all':
            # Remove from all one_time entries
            for cmd_hash in list(self.granted_permissions['one_time'].keys()):
                self.granted_permissions['one_time'][cmd_hash] -= permissions
                if not self.granted_permissions['one_time'][cmd_hash]:
                    del self.granted_permissions['one_time'][cmd_hash]
        self.updated_at = datetime.now()
        self.messages = []
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.
    
    Sessions are stored as JSONL files in the sessions directory.
    """
    
    def __init__(
        self,
        workspace: Path,
        model: list[str],
        provider: "LLMProvider | None" = None,
        consolidation_model: str | None = None,
    ):
        """Initialize SessionManager.
        
        Args:
            workspace: Workspace path for memory storage
            model: List of available models
            provider: Optional LLM provider for memory consolidation
            consolidation_model: Model to use for consolidation (defaults to first model)
        """
        self.workspace = workspace
        self.sessions_dir = ensure_dir(Path.home() / ".nanobot" / "sessions")
        self.models = model
        self.default_model = model[0]
        
        # Provider for memory consolidation
        self.provider = provider
        self.consolidation_model = consolidation_model or self.default_model
        
        self._cache: dict[str, Session] = {}  # session_id -> Session
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
    
    def _get_session_path(self, session_id: str) -> Path:
        """Get the file path for a session by session_id."""
        safe_key = safe_filename(session_id.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"
    
    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.
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
            
            # Try to load from disk
            session = self._load(session_id)
            if session:
                self._cache[session_id] = session
                return session
            else:
                # Session file missing, create new one
                logger.warning(f"Session {session_id} not found, creating new one")
        
        # Create new session
        return self.create_new_session(key)

    
    def _load(self, session_id: str) -> Session | None:
        """Load a session from disk by session_id."""
        path = self._get_session_path(session_id)
        
        if not path.exists():
            return None
        
        try:
            messages = []
            metadata = {}
            created_at = None
            config = SessionConfig()
            granted_permissions = {'persistent': set(), 'one_time': {}}
            
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    data = json.loads(line)
                    
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        # Load config if present
                        if "config" in data:
                            config = SessionConfig.from_dict(data["config"])
                        # Load granted_permissions if present
                        if "granted_permissions" in data:
                            perms_data = data["granted_permissions"]
                            granted_permissions = {
                                'persistent': set(perms_data.get("persistent", [])),
                                'one_time': {k: set(v) for k, v in perms_data.get("one_time", {}).items()}
                            }
                    else:
                        messages.append(data)
            
            return Session(
                key=session_id,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                config=config,
                granted_permissions=granted_permissions
            )
        except Exception as e:
            logger.warning(f"Failed to load session {session_id}: {e}")
            return None
    
    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)
        
        with open(path, "w") as f:
            # Write metadata first
            metadata_line = {
                "_type": "metadata",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "config": session.config.to_dict(),  # Save session config
                "granted_permissions": {
                    "persistent": list(session.granted_permissions.get("persistent", set())),
                    "one_time": {k: list(v) for k, v in session.granted_permissions.get("one_time", {}).items()}
                }
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            
            # Write messages
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        
        self._cache[session.key] = session
    
    async def consolidate_memory(
        self,
        session: Session,
        memory_window: int = 50,
        archive_all: bool = False,
    ) -> None:
        """
        Consolidate Session memory into MEMORY.md and HISTORY.md.
        
        This is part of Session lifecycle management:
        - Called automatically when Session is too long
        - Optionally called when creating a new Session
        - Uses LLM to generate summaries and update long-term memory
        
        Args:
            session: The session to consolidate
            memory_window: Maximum messages to keep in session
            archive_all: If True, archive all messages (for /new command)
        """
        if not self.provider:
            logger.warning("No provider available for memory consolidation")
            return
        
        if not session.messages:
            return
        
        # Import at runtime to avoid circular dependency
        from nanobot.agent.memory import MemoryStore
        
        memory = MemoryStore(self.workspace)
        
        # Determine which messages to archive
        if archive_all:
            old_messages = session.messages
            keep_count = 0
        else:
            keep_count = min(10, max(2, memory_window // 2))
            old_messages = session.messages[:-keep_count]
        
        if not old_messages:
            return
        
        logger.info(
            f"Memory consolidation: {len(session.messages)} messages, "
            f"archiving {len(old_messages)}, keeping {keep_count}"
        )
        
        # Format messages for LLM
        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = (
                f" [tools: {', '.join(m['tools_used'])}]"
                if m.get("tools_used")
                else ""
            )
            timestamp = m.get("timestamp", "?")[:16]
            lines.append(
                f"[{timestamp}] {m['role'].upper()}{tools}: {m['content']}"
            )
        
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
            response = await self.provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a memory consolidation agent. Respond only with valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                model=self.consolidation_model,
            )
            
            text = (response.content or "").strip()
            
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            result = json.loads(text)
            
            # Update history file
            if entry := result.get("history_entry"):
                memory.append_history(entry)
            
            # Update long-term memory
            if update := result.get("memory_update"):
                if update != current_memory:
                    memory.write_long_term(update)
            
            # Trim session
            session.messages = session.messages[-keep_count:] if keep_count else []
            
            logger.info(
                f"Memory consolidation done, session trimmed to {len(session.messages)} messages"
            )
            
        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")
    
    def create_new_session(
        self,
        user_key: str,
    ) -> Session:
        """
        Create a new session for a user and switch to it.
        
        Args:
            user_key: The user key (channel:chat_id)
            consolidate_old: Whether to consolidate old session's memory
        
        Returns:
            The new Session object
        """
        import uuid
        # Create new session
        session_id = uuid.uuid4().hex[:12]
        session = Session(key=session_id)
        session.config.model = self.default_model
        
        # Update mapping
        old_session_id = self.session_table.get(user_key)
        self.session_table[user_key] = session_id
        self._save_session_table()
        
        # Cache it
        self._cache[session_id] = session
        self.save(session)
        
        logger.info(f"Created new session {session_id} for {user_key} (previous: {old_session_id})")
        return session
    
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
    
    def get_user_sessions(self, user_key) -> list[str]:
        """
        Get all session_ids that belong to a user.
        Returns:
            List of session_ids
        """

        # This is a simple implementation; you might want to track this explicitly
        return [sid for uk, sid in self.session_table.items() if uk == user_key]
    
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
    
    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.
        
        Returns:
            List of session info dicts with message counts.
        """
        sessions = []
        
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                session_id = path.stem.replace("_", ":")
                session = self._load(session_id)
                
                if session:
                    sessions.append({
                        "key": session.key,
                        "created_at": session.created_at.isoformat(),
                        "updated_at": session.updated_at.isoformat(),
                        "message_count": len(session.messages),
                        "path": str(path)
                    })
            except Exception as e:
                logger.warning(f"Failed to load session {path.stem}: {e}")
                continue
        
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

    
    def get_session_model(self, user_key) -> str:
        """
        Get the model for a session.
        Returns:
            The model name (session-specific or default).
        """
        session = self.get_or_create(user_key)
        return session.config.model or self.default_model
    
    def set_session_model(self, user_key, model: str) -> None:
        """
        Set the model for a session.
        """
        session = self.get_or_create(user_key)
        session.config.model = model
        self.save(session)
    
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
            "model": session.config.model or self.default_model,
            "is_custom_model": session.config.model is not None,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "max_iterations": session.config.max_iterations,
            "temperature": session.config.temperature,
            "permissions": {
                "persistent": list(session.granted_permissions.get("persistent", set())),
                "one_time": {k: list(v) for k, v in session.granted_permissions.get("one_time", {}).items()}
            }
        }
