"""Memory tools for updating session state."""

from typing import Any, Optional

from nanobot.agent.tools.base import Tool
from nanobot.session.manager import SessionManager


class UpdateSessionMemoryTool(Tool):
    """Tool to update session-specific memory."""
    
    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self._channel: Optional[str] = None
        self._chat_id: Optional[str] = None
        
    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current session context."""
        self._channel = channel
        self._chat_id = chat_id
        
    @property
    def name(self) -> str:
        return "update_session_memory"
        
    @property
    def description(self) -> str:
        return "Update session-specific memory (customer profile, contacts). ONLY use this when user explicitly says '更新会话记忆' or similar commands."
        
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "website_domain": {
                    "type": "string",
                    "description": "Customer's website domain"
                },
                "brand_intro": {
                    "type": "string",
                    "description": "Brief introduction of the brand"
                },
                "business_type": {
                    "type": "string",
                    "description": "Type of business (e.g., e-commerce, SaaS)"
                },
                "contacts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "role": {"type": "string"}
                        },
                        "required": ["name"]
                    },
                    "description": "List of contacts"
                }
            }
        }
        
    async def execute(self, **kwargs: Any) -> str:
        if not self._channel or not self._chat_id:
            return "Error: No active session context"
            
        session_key = f"{self._channel}:{self._chat_id}"
        session = self.session_manager.get_or_create(session_key)
        
        updates = []
        
        # Update customer profile fields
        profile_fields = ["website_domain", "brand_intro", "business_type"]
        if "customer_profile" not in session.metadata:
            session.metadata["customer_profile"] = {}
            
        for field in profile_fields:
            if field in kwargs:
                session.metadata["customer_profile"][field] = kwargs[field]
                updates.append(field)
                
        # Update contacts
        if "contacts" in kwargs:
            session.metadata["contacts"] = kwargs["contacts"]
            updates.append("contacts")
            
        if not updates:
            return "No updates provided."
            
        self.session_manager.save(session)
        return f"Successfully updated session memory: {', '.join(updates)}"
