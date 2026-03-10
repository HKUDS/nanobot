"""A2A client tool for calling external A2A agents.

This tool allows nanobot to communicate with other A2A-compatible agents,
enabling multi-agent workflows and delegation.

See: https://a2a-protocol.org
"""

import json
from typing import Any
from uuid import uuid4

from loguru import logger

from nanobot.agent.tools.base import Tool

try:
    import httpx
    from a2a.client import A2ACardResolver, A2AClient
    from a2a.types import (
        MessageSendParams,
        SendMessageRequest,
    )
    A2A_CLIENT_AVAILABLE = True
except ImportError:
    A2A_CLIENT_AVAILABLE = False


class A2AClientTool(Tool):
    """
    Call an external A2A agent to perform a task.
    
    Use this tool when you need capabilities from another specialized agent,
    such as:
    - A travel booking agent
    - A data analysis agent
    - A code review agent
    - Any other A2A-compatible service
    
    The tool will:
    1. Discover the agent's capabilities via its Agent Card
    2. Send your message to the agent
    3. Return the agent's response
    """
    
    def __init__(self, timeout: int = 120):
        """
        Initialize the A2A client tool.
        
        Args:
            timeout: Request timeout in seconds.
        """
        self._timeout = timeout
    
    @property
    def name(self) -> str:
        return "call_a2a_agent"
    
    @property
    def description(self) -> str:
        return """Call an external A2A agent to perform a task.

Use this when you need specialized capabilities from another agent.
First, you can optionally discover what the agent can do, then send your request.

Args:
    agent_url: The base URL of the A2A agent (e.g., "https://travel-agent.example.com")
    message: The message/task to send to the agent
    discover_only: If true, only return the agent's capabilities without sending a message

Returns:
    If discover_only: The agent's capabilities and skills
    Otherwise: The agent's response to your message

Examples:
    - call_a2a_agent("https://travel.example.com", "Book a flight to Paris for next Monday")
    - call_a2a_agent("https://code-review.example.com", "Review this Python function: ...")
    - call_a2a_agent("https://unknown-agent.example.com", "", discover_only=True)
"""
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_url": {
                    "type": "string",
                    "description": "Base URL of the A2A agent (e.g., https://agent.example.com)",
                },
                "message": {
                    "type": "string",
                    "description": "Message or task to send to the agent",
                },
                "discover_only": {
                    "type": "boolean",
                    "description": "If true, only discover the agent's capabilities without sending a message",
                },
            },
            "required": ["agent_url"],
        }
    
    async def execute(
        self,
        agent_url: str,
        message: str = "",
        discover_only: bool = False,
        **kwargs: Any,
    ) -> str:
        """
        Execute an A2A call to an external agent.
        
        Args:
            agent_url: Base URL of the target A2A agent.
            message: Message to send (required if not discover_only).
            discover_only: If true, only fetch and return the agent card.
        
        Returns:
            Agent's response or capabilities description.
        """
        if not A2A_CLIENT_AVAILABLE:
            return "Error: A2A client not available. Install with: pip install 'a2a-sdk[http-server]'"
        
        if not discover_only and not message:
            return "Error: message is required when discover_only is False"
        
        # Normalize URL
        agent_url = agent_url.rstrip("/")
        
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as httpx_client:
                # Resolve the agent card
                resolver = A2ACardResolver(
                    httpx_client=httpx_client,
                    base_url=agent_url,
                )
                
                try:
                    agent_card = await resolver.get_agent_card()
                except Exception as e:
                    return f"Error: Could not discover agent at {agent_url}. Is it running? ({e})"
                
                logger.info(f"Discovered A2A agent: {agent_card.name}")
                
                # If discover_only, return the agent's capabilities
                if discover_only:
                    return self._format_agent_card(agent_card)
                
                # Create the A2A client
                client = A2AClient(
                    httpx_client=httpx_client,
                    agent_card=agent_card,
                )
                
                # Build the message request
                message_id = uuid4().hex
                send_payload = {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": message}],
                        "messageId": message_id,
                    }
                }
                
                request = SendMessageRequest(
                    id=str(uuid4()),
                    params=MessageSendParams(**send_payload),
                )
                
                logger.info(f"Sending message to {agent_card.name}: {message[:100]}...")
                
                # Send the message
                response = await client.send_message(request)
                
                # Extract the response text
                return self._extract_response(response, agent_card.name)
                
        except Exception as e:
            if "timeout" in str(e).lower():
                return f"Error: Request to {agent_url} timed out after {self._timeout}s"
            logger.error(f"A2A client error: {e}")
            return f"Error calling A2A agent: {e}"
    
    def _format_agent_card(self, card: Any) -> str:
        """Format an agent card as a readable string."""
        lines = [
            f"# Agent: {card.name}",
            f"**Description:** {card.description}",
            f"**URL:** {card.url}",
            f"**Version:** {card.version}",
            "",
            "## Capabilities",
            f"- Streaming: {card.capabilities.streaming if card.capabilities else 'unknown'}",
            "",
            "## Skills",
        ]
        
        if card.skills:
            for skill in card.skills:
                lines.append(f"\n### {skill.name}")
                lines.append(f"*{skill.description}*")
                if skill.examples:
                    lines.append("\nExamples:")
                    for example in skill.examples[:3]:  # Limit examples
                        lines.append(f"  - {example}")
        else:
            lines.append("No specific skills advertised.")
        
        return "\n".join(lines)
    
    def _extract_response(self, response: Any, agent_name: str) -> str:
        """Extract text content from an A2A response."""
        try:
            # The response structure varies, try common patterns
            result = response.result
            
            # Check for artifacts
            if hasattr(result, 'artifacts') and result.artifacts:
                texts = []
                for artifact in result.artifacts:
                    if hasattr(artifact, 'parts'):
                        for part in artifact.parts:
                            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                texts.append(part.root.text)
                            elif hasattr(part, 'text'):
                                texts.append(part.text)
                if texts:
                    return "\n".join(texts)
            
            # Check for history (conversation-style response)
            if hasattr(result, 'history') and result.history:
                for msg in reversed(result.history):
                    if hasattr(msg, 'role') and msg.role == 'agent':
                        if hasattr(msg, 'parts'):
                            for part in msg.parts:
                                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                    return part.root.text
                                elif hasattr(part, 'text'):
                                    return part.text
            
            # Check for status
            if hasattr(result, 'status'):
                status = result.status
                if hasattr(status, 'message') and status.message:
                    if hasattr(status.message, 'parts'):
                        for part in status.message.parts:
                            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                return part.root.text
                            elif hasattr(part, 'text'):
                                return part.text
            
            # Fallback: serialize the result
            if hasattr(result, 'model_dump'):
                return f"Response from {agent_name}:\n```json\n{json.dumps(result.model_dump(exclude_none=True), indent=2)}\n```"
            
            return f"Agent {agent_name} completed the task but returned no extractable text."
            
        except Exception as e:
            logger.warning(f"Error extracting A2A response: {e}")
            return f"Agent {agent_name} responded but the response format was unexpected: {e}"


# Alias for backwards compatibility
A2AAgentTool = A2AClientTool
