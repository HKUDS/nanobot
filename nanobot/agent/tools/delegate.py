import asyncio
import uuid
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


class AgentDelegateTool(Tool):
    """Tool to delegate tasks to peer agents running in the same process."""

    def __init__(self, peer_buses: dict[str, MessageBus], 
                 allowed_agent_delegates: list[str], 
                 peer_profiles: dict[str, str],
                 self_agent_name: str,
                 main_bus: MessageBus | None = None):
        self._buses = peer_buses
        self._allowed = allowed_agent_delegates
        self._profiles = peer_profiles
        self._self_name = self_agent_name
        self._origin_channel = "system"
        self._origin_chat_id = "delegate"
        self._main_bus = main_bus
        self._pending_tasks: dict[str, asyncio.Future] = {}

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the calling context so the remote agent knows where to reply."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    @property
    def name(self) -> str:
        return "agent_delegate"

    @property
    def description(self) -> str:
        allowed = []
        for name in self._buses.keys():
            if "*" in self._allowed or name in self._allowed:
                allowed.append(name)
                
        if not allowed:
            return "No peer agents are available or authorized to be delegated to."

        # Compile the comprehensive manual from peer instances
        manual = []
        for name in allowed:
            prof = self._profiles.get(name, "No description available.")
            manual.append(f"[{name}]\n{prof}")
            
        compiled_manual = "\n---\n".join(manual)
            
        return (
            "Delegate a task to an independent peer agent.\n"
            "This command passes the task to the peer agent and blocks until they finish.\n"
            "When the peer agent finishes, their results will be returned directly as the output of this tool.\n\n"
            "AVAILABLE PEER AGENTS (and their capabilities):\n"
            f"{compiled_manual}"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "The exact name of the peer agent to delegate to (e.g. from the list above).",
                },
                "task": {
                    "type": "string",
                    "description": "The specific, detailed task instructions and all relevant context needed for them to operate independently.",
                },
            },
            "required": ["agent_name", "task"],
        }

    async def execute(self, agent_name: str, task: str, **kwargs: Any) -> str:
        """Publish an InboundMessage to the peer agent's MessageBus and wait."""
        if agent_name not in self._buses:
            return f"Error: Peer agent '{agent_name}' not found."
            
        if "*" not in self._allowed and agent_name not in self._allowed:
            return f"Error: You do not have permission to delegate tasks to '{agent_name}'. Allowed: {', '.join(self._allowed)}"

        bus = self._buses[agent_name]
        task_id = str(uuid.uuid4())
        future = asyncio.Future()
        self._pending_tasks[task_id] = future
        
        # We spoof the source as "system" so the peer knows it's an internal background task
        # We specify "delegated_from" metadata so that the peer's forwarder intercepts the reply.
        msg = InboundMessage(
            channel="system",
            sender_id=f"peer:{self._self_name}",
            chat_id=f"{self._origin_channel}:{self._origin_chat_id}",
            content=task,
            metadata={
                "delegated_from": self._self_name,
                "delegate_task_id": task_id,
                "delegate_task_target": agent_name,
            }
        )
        
        await bus.publish_inbound(msg)
        logger.info(f"[{self._self_name}] Delegated task {task_id} to '{agent_name}', waiting for result...")
        
        try:
            result = await future
            return f"{agent_name} replied:\n{result}"
        except asyncio.CancelledError:
            logger.info(f"[{self._self_name}] Delegated task {task_id} to '{agent_name}' was cancelled. Sending /stop to peer.")
            # Send stop to the peer agent
            stop_msg = InboundMessage(
                channel="system",
                sender_id=f"peer:{self._self_name}",
                chat_id=f"{self._origin_channel}:{self._origin_chat_id}",
                content="/stop",
            )
            await bus.publish_inbound(stop_msg)
            raise
        finally:
            self._pending_tasks.pop(task_id, None)

    async def resolve_task(self, task_id: str, is_final: bool, content: str) -> None:
        """Resolve a pending task with a result from the peer agent."""
        future = self._pending_tasks.get(task_id)
        if not future:
            return

        if not is_final:
            # Emit progress horizontally
            if self._main_bus:
                await self._main_bus.publish_outbound(OutboundMessage(
                    channel=self._origin_channel,
                    chat_id=self._origin_chat_id,
                    content=content,
                    metadata={"_progress": True, "_tool_hint": False}
                ))
            return
            
        if not future.done():
            future.set_result(content)
