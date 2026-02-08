"""Reasoning tools: sequential thinking and planning."""

from typing import Any, Optional

from nanobot.agent.tools.base import Tool


class SequentialThinkingTool(Tool):
    """Tool for dynamic multi-step planning and reflection."""
    
    @property
    def name(self) -> str:
        return "sequential_thinking"
    
    @property
    def description(self) -> str:
        return "Plan, reflect, and track progress over multiple steps."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "thought": {
                    "type": "string",
                    "description": "The thought, plan, or reflection content"
                },
                "next_thought_needed": {
                    "type": "boolean",
                    "description": "True if you need another thinking step, False if ready to act"
                },
                "thought_number": {
                    "type": "integer",
                    "description": "Current thought number (1-based)"
                },
                "total_thoughts": {
                    "type": "integer",
                    "description": "Estimated total thoughts"
                },
                "is_revision": {
                    "type": "boolean",
                    "description": "Whether this revises a previous thought"
                },
                "revises_thought": {
                    "type": "integer",
                    "description": "The thought number being revised"
                },
                "branch_from_thought": {
                    "type": "integer",
                    "description": "The thought number to branch from"
                },
                "branch_id": {
                    "type": "string",
                    "description": "Identifier for the branch"
                }
            },
            "required": ["thought", "next_thought_needed", "thought_number", "total_thoughts"]
        }
    
    async def execute(
        self,
        thought: str,
        next_thought_needed: bool,
        thought_number: int,
        total_thoughts: int,
        is_revision: Optional[bool] = False,
        revises_thought: Optional[int] = None,
        branch_from_thought: Optional[int] = None,
        branch_id: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        status = "continuing" if next_thought_needed else "ready to act"
        
        meta_info = []
        if is_revision:
            meta_info.append(f"Rev. {revises_thought}")
        if branch_from_thought:
            meta_info.append(f"Branch {branch_id} from {branch_from_thought}")
            
        meta_str = f" [{', '.join(meta_info)}]" if meta_info else ""
        
        return f"Thought {thought_number}/{total_thoughts}{meta_str}: {thought} (Status: {status})"
