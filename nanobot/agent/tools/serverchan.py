from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.config.schema import ServerchanToolConfig

from serverchan_sdk import sc_send
from loguru import logger

class ServerchanPushTool(Tool):
    def __init__(self, config: ServerchanToolConfig):
        super().__init__()
        self.send_key = config.send_key

    @property
    def name(self) -> str:
        return "Serverchan Push"
    
    @property
    def description(self) -> str:
        return "Push Message, Notification, Alert To User via Serverchan"
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The Message, Notification, Alert title. Concise and refined, emojis can be used"
                },
                "desp": {
                    "type": "string",
                    "description": "The detail of Message, Notification, Alert. Using Markdown"
                },
                "tags": {
                    "type": "string",
                    "description": "the tags of the message, split by '|'"
                }
            },
            "required": ["title", "desp"],
        }
    
    async def execute(self, 
        title: str = "",
        desp: str = "",
        tags: str = "",              
        **kwargs: Any) -> str:
        """
        Execute the tool with given parameters.
        
        Args:
            **kwargs: Tool-specific parameters.
        
        Returns:
            String result of the tool execution.
        """
        try:
            response = sc_send(self.send_key, title, desp, {"tags": tags})
            logger.debug(f"Serverchan Push Result: {response["message"]}")
            return f"Serverchan Push Result: {response["message"]}"
        except Exception as e:
            return f"Serverchan Push Error: {str(e)}"