"""A2A Protocol channel implementation.

This channel allows nanobot to receive requests from other A2A-compatible agents,
turning nanobot into a discoverable AI service.

See: https://a2a-protocol.org
"""

import asyncio
from typing import Any, AsyncIterator
from uuid import uuid4

from loguru import logger

try:
    from a2a.server.apps import A2AStarletteApplication
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    from a2a.server.events import EventQueue
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import (
        AgentCapabilities,
        AgentCard,
        AgentSkill,
        Part,
        TextPart,
    )
    from a2a.utils import new_agent_text_message, completed_task, new_artifact

    A2A_AVAILABLE = True
except ImportError:
    A2A_AVAILABLE = False

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import A2AConfig


class NanobotAgentExecutor(AgentExecutor):
    """
    A2A AgentExecutor that routes requests through nanobot's message bus.
    
    This bridges the A2A protocol to nanobot's internal message handling,
    allowing the agent loop to process A2A requests like any other channel.
    """
    
    def __init__(self, bus: MessageBus, config: A2AConfig):
        self.bus = bus
        self.config = config
        self._pending_responses: dict[str, asyncio.Future[str]] = {}
    
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """
        Execute an A2A request by routing through nanobot's agent loop.
        
        Args:
            context: The A2A request context containing the message.
            event_queue: Queue for sending events back to the A2A client.
        """
        # Extract user input from the A2A message
        user_input = context.get_user_input()
        if not user_input:
            await event_queue.enqueue_event(
                new_agent_text_message("I didn't receive any message content.")
            )
            return
        
        task_id = context.task_id or uuid4().hex
        context_id = context.context_id or uuid4().hex
        
        logger.info(f"A2A request received: task={task_id}, input={user_input[:100]}...")
        
        # Create a future to wait for the response
        response_future: asyncio.Future[str] = asyncio.Future()
        response_key = f"a2a:{task_id}"
        self._pending_responses[response_key] = response_future
        
        try:
            # Create an inbound message and publish to the bus
            msg = InboundMessage(
                channel="a2a",
                sender_id=f"a2a:{context_id}",
                chat_id=task_id,
                content=user_input,
                metadata={
                    "task_id": task_id,
                    "context_id": context_id,
                    "a2a_request": True,
                }
            )
            
            await self.bus.publish_inbound(msg)
            
            # Wait for response with timeout
            timeout = self.config.request_timeout
            try:
                response = await asyncio.wait_for(response_future, timeout=timeout)
            except asyncio.TimeoutError:
                response = f"Request timed out after {timeout} seconds."
                logger.warning(f"A2A request {task_id} timed out")
            
            # Send the response back through A2A
            await event_queue.enqueue_event(new_agent_text_message(response))
            
        finally:
            # Clean up
            self._pending_responses.pop(response_key, None)
    
    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Cancel a running task."""
        task_id = context.task_id
        response_key = f"a2a:{task_id}"
        
        if response_key in self._pending_responses:
            future = self._pending_responses.pop(response_key)
            if not future.done():
                future.set_result("Task was cancelled.")
        
        logger.info(f"A2A task {task_id} cancelled")
    
    def complete_request(self, task_id: str, response: str) -> bool:
        """
        Complete a pending A2A request with a response.
        
        Called by the A2A channel when an outbound message is received.
        
        Args:
            task_id: The task ID to complete.
            response: The response content.
            
        Returns:
            True if a pending request was found and completed.
        """
        response_key = f"a2a:{task_id}"
        future = self._pending_responses.get(response_key)
        
        if future and not future.done():
            future.set_result(response)
            return True
        
        return False


def build_agent_card(config: A2AConfig, name: str, description: str) -> AgentCard:
    """
    Build an A2A Agent Card from nanobot configuration.
    
    The Agent Card is the discovery document that tells other agents
    what this agent can do.
    
    Args:
        config: A2A channel configuration.
        name: Agent name.
        description: Agent description.
    
    Returns:
        An AgentCard describing this nanobot instance.
    """
    # Define the default skill (general assistant)
    skills = [
        AgentSkill(
            id="assistant",
            name="General Assistant",
            description="Full-stack AI assistant with tools for code, search, memory, and more.",
            tags=["assistant", "coding", "search", "memory"],
            examples=[
                "Search the web for recent AI news",
                "Write a Python function to sort a list",
                "Help me debug this code",
            ],
        )
    ]
    
    # Add custom skills from config
    for skill_cfg in config.skills:
        skills.append(AgentSkill(
            id=skill_cfg.get("id", "custom"),
            name=skill_cfg.get("name", "Custom Skill"),
            description=skill_cfg.get("description", ""),
            tags=skill_cfg.get("tags", []),
            examples=skill_cfg.get("examples", []),
        ))
    
    # Build the URL
    host = config.public_host or f"http://localhost:{config.port}"
    url = f"{host.rstrip('/')}"
    
    return AgentCard(
        name=name,
        description=description,
        url=url,
        version="0.1.3",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(
            streaming=config.streaming,
            push_notifications=False,
        ),
        skills=skills,
    )


class A2AChannel(BaseChannel):
    """
    A2A Protocol channel for nanobot.
    
    Exposes nanobot as an A2A-compatible agent that other agents can discover
    and communicate with using the Agent-to-Agent protocol.
    
    Features:
    - Agent Card at /.well-known/agent.json
    - JSON-RPC endpoint for message/send and message/stream
    - Integration with nanobot's agent loop via the message bus
    """
    
    name = "a2a"
    
    def __init__(
        self,
        config: A2AConfig,
        bus: MessageBus,
        agent_name: str = "nanobot",
        agent_description: str = "Ultra-lightweight AI assistant",
    ):
        if not A2A_AVAILABLE:
            raise ImportError(
                "A2A SDK not installed. Install with: pip install 'a2a-sdk[http-server]'"
            )
        
        super().__init__(config, bus)
        self.config: A2AConfig = config
        self.agent_name = agent_name
        self.agent_description = agent_description
        
        # Create the executor that bridges A2A to nanobot
        self.executor = NanobotAgentExecutor(bus, config)
        
        # Build the A2A application
        self.agent_card = build_agent_card(
            config, agent_name, agent_description
        )
        
        self.request_handler = DefaultRequestHandler(
            agent_executor=self.executor,
            task_store=InMemoryTaskStore(),
        )
        
        self.a2a_app = A2AStarletteApplication(
            agent_card=self.agent_card,
            http_handler=self.request_handler,
        )
        
        self._server: Any = None
        self._serve_task: asyncio.Task | None = None
    
    async def start(self) -> None:
        """Start the A2A server."""
        import uvicorn
        
        self._running = True
        
        logger.info(f"Starting A2A server on {self.config.host}:{self.config.port}")
        logger.info(f"Agent Card: http://{self.config.host}:{self.config.port}/.well-known/agent.json")
        
        # Build the Starlette app
        app = self.a2a_app.build()
        
        # Configure uvicorn
        uvi_config = uvicorn.Config(
            app,
            host=self.config.host,
            port=self.config.port,
            log_level="warning",  # Reduce noise
        )
        
        self._server = uvicorn.Server(uvi_config)
        
        # Run the server
        await self._server.serve()
    
    async def stop(self) -> None:
        """Stop the A2A server."""
        self._running = False
        
        if self._server:
            logger.info("Stopping A2A server...")
            self._server.should_exit = True
            self._server = None
    
    async def send(self, msg: OutboundMessage) -> None:
        """
        Handle an outbound message for the A2A channel.
        
        This completes pending A2A requests with the response from the agent loop.
        
        Args:
            msg: The outbound message containing the response.
        """
        task_id = msg.chat_id
        
        # Complete the pending A2A request
        if self.executor.complete_request(task_id, msg.content):
            logger.debug(f"A2A response sent for task {task_id}")
        else:
            logger.warning(f"No pending A2A request for task {task_id}")


async def start_a2a_channel(
    config: A2AConfig,
    bus: MessageBus,
    agent_name: str = "nanobot",
    agent_description: str = "Ultra-lightweight AI assistant",
) -> A2AChannel:
    """
    Create and start an A2A channel.
    
    Args:
        config: A2A configuration.
        bus: The message bus.
        agent_name: Name for the agent card.
        agent_description: Description for the agent card.
    
    Returns:
        The started A2A channel.
    """
    channel = A2AChannel(
        config=config,
        bus=bus,
        agent_name=agent_name,
        agent_description=agent_description,
    )
    
    await channel.start()
    return channel
