"""
Named Topics Tool - Context switching within a single chat.

Allows users to create multiple named "topics" within a single chat,
each with isolated conversation context. Useful for separating
work, personal, projects without needing Telegram forum mode.
"""

import json
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


def _get_topics_file(channel: str, chat_id: str) -> Path:
    """Get the topics storage file for a chat."""
    topics_dir = Path.home() / ".nanobot" / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    return topics_dir / f"{channel}_{chat_id}.json"


def _load_topics(channel: str, chat_id: str) -> dict:
    """Load topics from storage."""
    file = _get_topics_file(channel, chat_id)
    if file.exists():
        return json.loads(file.read_text())
    return {"topics": {}, "current": None}


def _save_topics(channel: str, chat_id: str, data: dict) -> None:
    """Save topics to storage."""
    file = _get_topics_file(channel, chat_id)
    file.write_text(json.dumps(data, indent=2))


def _get_session_with_topic(session_key: str, topic: str | None) -> str:
    """Build session key with topic suffix."""
    if not session_key:
        return session_key
    parts = session_key.split(":")
    if len(parts) < 2:
        return session_key
    channel, chat_id = parts[0], parts[1]
    if topic:
        return f"{channel}:{chat_id}:{topic}"
    return f"{channel}:{chat_id}"


class TopicTool(Tool):
    """Manage named topics for context isolation."""
    
    name = "topic"
    description = "Manage named topics for context switching. Actions: list, current, create, switch, delete."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "current", "create", "switch", "delete"],
                "description": "Action to perform"
            },
            "name": {
                "type": "string",
                "description": "Topic name (for create, switch, delete)"
            }
        },
        "required": ["action"]
    }
    
    def execute(
        self,
        action: str,
        name: str | None = None,
        session_key: str | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """Execute a topic action."""
        # Parse session_key to get channel and chat_id
        if not session_key:
            return {"error": "No session key provided"}
        
        parts = session_key.split(":")
        if len(parts) < 2:
            return {"error": f"Invalid session key: {session_key}"}
        
        channel = parts[0]
        chat_id = parts[1]
        
        data = _load_topics(channel, chat_id)
        
        if action == "list":
            topics = data.get("topics", {})
            current = data.get("current")
            
            if not topics:
                return {"message": "No topics exist. Use /topic create <name> to create one."}
            
            lines = ["📁 Topics:"]
            for topic_name in sorted(topics.keys()):
                marker = "📌 " if topic_name == current else "   "
                lines.append(f"{marker}{topic_name}")
            
            return {"message": "\n".join(lines)}
        
        elif action == "current":
            current = data.get("current")
            if current:
                return {"message": f"📌 Current topic: {current}"}
            else:
                return {"message": "No topic active (default context)"}
        
        elif action == "create":
            if not name:
                return {"error": "Topic name required"}
            
            # Validate name
            if not name.replace("-", "").replace("_", "").isalnum():
                return {"error": "Topic name must be alphanumeric (hyphens and underscores allowed)"}
            
            if len(name) > 64:
                return {"error": "Topic name must be 64 characters or less"}
            
            topics = data.get("topics", {})
            if name in topics:
                return {"error": f"Topic '{name}' already exists"}
            
            # Create topic and switch to it
            topics[name] = {"created_at": kwargs.get("timestamp")}
            data["topics"] = topics
            data["current"] = name
            _save_topics(channel, chat_id, data)
            
            return {
                "message": f"✅ Created and switched to topic: {name}",
                "topic": name,
                "session_key": f"{channel}:{chat_id}:{name}"
            }
        
        elif action == "switch":
            if not name:
                return {"error": "Topic name required"}
            
            topics = data.get("topics", {})
            if name not in topics:
                return {"error": f"Topic '{name}' does not exist. Available: {', '.join(sorted(topics.keys())) or 'none'}"}
            
            data["current"] = name
            _save_topics(channel, chat_id, data)
            
            return {
                "message": f"📌 Switched to topic: {name}",
                "topic": name,
                "session_key": f"{channel}:{chat_id}:{name}"
            }
        
        elif action == "delete":
            if not name:
                return {"error": "Topic name required"}
            
            topics = data.get("topics", {})
            if name not in topics:
                return {"error": f"Topic '{name}' does not exist"}
            
            del topics[name]
            data["topics"] = topics
            
            # If deleting current topic, reset to default
            if data.get("current") == name:
                data["current"] = None
            
            _save_topics(channel, chat_id, data)
            
            return {
                "message": f"🗑️ Deleted topic: {name}",
                "topic": None,
                "session_key": f"{channel}:{chat_id}"
            }
        
        else:
            return {"error": f"Unknown action: {action}"}


# Individual action tools for registration in loop.py

class ListTopicsTool(Tool):
    """List all topics."""
    name = "topic_list"
    description = "List all named topics in this chat."
    parameters = {"type": "object", "properties": {}}
    
    def execute(self, session_key: str | None = None, **kwargs) -> dict[str, Any]:
        if not session_key:
            return {"error": "No session key"}
        parts = session_key.split(":")
        if len(parts) < 2:
            return {"error": "Invalid session key"}
        
        data = _load_topics(parts[0], parts[1])
        topics = data.get("topics", {})
        current = data.get("current")
        
        if not topics:
            return {"message": "No topics exist. Use /topic create <name> to create one."}
        
        lines = ["📁 Topics:"]
        for name in sorted(topics.keys()):
            marker = "📌 " if name == current else "   "
            lines.append(f"{marker}{name}")
        
        return {"message": "\n".join(lines)}


class CurrentTopicTool(Tool):
    """Show current topic."""
    name = "topic_current"
    description = "Show the currently active topic."
    parameters = {"type": "object", "properties": {}}
    
    def execute(self, session_key: str | None = None, **kwargs) -> dict[str, Any]:
        if not session_key:
            return {"error": "No session key"}
        parts = session_key.split(":")
        if len(parts) < 2:
            return {"error": "Invalid session key"}
        
        data = _load_topics(parts[0], parts[1])
        current = data.get("current")
        
        if current:
            return {"message": f"📌 Current topic: {current}"}
        return {"message": "No topic active (default context)"}


class CreateTopicTool(Tool):
    """Create a new topic."""
    name = "topic_create"
    description = "Create a new named topic for context isolation."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Topic name (alphanumeric, hyphens, underscores)"
            }
        },
        "required": ["name"]
    }
    
    def execute(self, name: str, session_key: str | None = None, **kwargs) -> dict[str, Any]:
        if not session_key:
            return {"error": "No session key"}
        parts = session_key.split(":")
        if len(parts) < 2:
            return {"error": "Invalid session key"}
        
        if not name:
            return {"error": "Topic name required"}
        
        if not name.replace("-", "").replace("_", "").isalnum():
            return {"error": "Topic name must be alphanumeric (hyphens and underscores allowed)"}
        
        if len(name) > 64:
            return {"error": "Topic name must be 64 characters or less"}
        
        channel, chat_id = parts[0], parts[1]
        data = _load_topics(channel, chat_id)
        topics = data.get("topics", {})
        
        if name in topics:
            return {"error": f"Topic '{name}' already exists"}
        
        topics[name] = {}
        data["topics"] = topics
        data["current"] = name
        _save_topics(channel, chat_id, data)
        
        return {
            "message": f"✅ Created and switched to topic: {name}",
            "topic": name,
            "session_key": f"{channel}:{chat_id}:{name}"
        }


class SwitchTopicTool(Tool):
    """Switch to a topic."""
    name = "topic_switch"
    description = "Switch to an existing topic."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Topic name to switch to"
            }
        },
        "required": ["name"]
    }
    
    def execute(self, name: str, session_key: str | None = None, **kwargs) -> dict[str, Any]:
        if not session_key:
            return {"error": "No session key"}
        parts = session_key.split(":")
        if len(parts) < 2:
            return {"error": "Invalid session key"}
        
        if not name:
            return {"error": "Topic name required"}
        
        channel, chat_id = parts[0], parts[1]
        data = _load_topics(channel, chat_id)
        topics = data.get("topics", {})
        
        if name not in topics:
            return {"error": f"Topic '{name}' does not exist. Available: {', '.join(sorted(topics.keys())) or 'none'}"}
        
        data["current"] = name
        _save_topics(channel, chat_id, data)
        
        return {
            "message": f"📌 Switched to topic: {name}",
            "topic": name,
            "session_key": f"{channel}:{chat_id}:{name}"
        }


class DeleteTopicTool(Tool):
    """Delete a topic."""
    name = "topic_delete"
    description = "Delete a topic and its history."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Topic name to delete"
            }
        },
        "required": ["name"]
    }
    
    def execute(self, name: str, session_key: str | None = None, **kwargs) -> dict[str, Any]:
        if not session_key:
            return {"error": "No session key"}
        parts = session_key.split(":")
        if len(parts) < 2:
            return {"error": "Invalid session key"}
        
        if not name:
            return {"error": "Topic name required"}
        
        channel, chat_id = parts[0], parts[1]
        data = _load_topics(channel, chat_id)
        topics = data.get("topics", {})
        
        if name not in topics:
            return {"error": f"Topic '{name}' does not exist"}
        
        del topics[name]
        data["topics"] = topics
        
        if data.get("current") == name:
            data["current"] = None
        
        _save_topics(channel, chat_id, data)
        
        return {
            "message": f"🗑️ Deleted topic: {name}",
            "topic": None,
            "session_key": f"{channel}:{chat_id}"
        }


# Tool registry entry
TOOL = TopicTool