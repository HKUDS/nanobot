"""A2A Protocol channel using official a2a-sdk."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

if TYPE_CHECKING:
    from a2a.types import AgentCard, Task

try:
    from a2a.server.apps.jsonrpc.starlette_app import A2AStarletteApplication
    from a2a.server.request_handlers.request_handler import RequestHandler
    from a2a.server.context import ServerCallContext
    from a2a.types import (
        AgentCard as AgentCardType,
        AgentSkill,
        Message,
        MessageSendParams,
        Part,
        Task as TaskType,
        TaskQueryParams,
        TaskIdParams,
        TaskStatus,
        TaskState,
        TaskPushNotificationConfig,
        DeleteTaskPushNotificationConfigParams,
        GetTaskPushNotificationConfigParams,
        ListTaskPushNotificationConfigParams,
    )

    A2A_AVAILABLE = True
except ImportError:
    A2A_AVAILABLE = False
    A2AStarletteApplication = None
    RequestHandler = object
    AgentCardType = None
    AgentSkill = None
    ServerCallContext = None


class A2ARequestHandler(RequestHandler):
    """A2A request handler that bridges to Nanobot's message bus."""

    def __init__(self, channel: "A2AChannel"):
        self._channel = channel
        self._pending_tasks: dict[str, asyncio.Future[str]] = {}
        self._context_to_task: dict[str, str] = {}

    async def on_message_send(
        self,
        params: MessageSendParams,
        context: ServerCallContext | None = None,
    ) -> TaskType:
        """Handle message/send - create task and route to bus."""
        if not A2A_AVAILABLE:
            raise RuntimeError("a2a-sdk not installed")

        message = params.message
        # Get or generate context_id
        if message and message.context_id:
            context_id = message.context_id
        else:
            context_id = f"a2a:{uuid.uuid4().hex[:12]}"
        
        content = self._extract_content(message)
        task_id = uuid.uuid4().hex[:12]

        response_future: asyncio.Future[str] = asyncio.Future()
        self._pending_tasks[task_id] = response_future
        self._context_to_task[context_id] = task_id

        inbound = InboundMessage(
            channel="a2a",
            sender_id=message.role if message else "a2a-client",
            chat_id=context_id,
            content=content,
            metadata={"task_id": task_id, "a2a_context_id": context_id},
            session_key_override=context_id,
        )

        await self._channel.bus.publish_inbound(inbound)
        logger.debug("A2A task {} published to bus", task_id)

        task = TaskType(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.working),
        )

        asyncio.create_task(self._wait_for_response(task_id, context_id, response_future))

        return task

    async def on_message_send_stream(
        self,
        params: MessageSendParams,
        context: ServerCallContext | None = None,
    ) -> AsyncGenerator[Any, None]:
        """Handle message/send streaming (not implemented)."""
        # For now, just delegate to non-streaming
        task = await self.on_message_send(params, context)
        yield task

    async def _wait_for_response(
        self,
        task_id: str,
        context_id: str,
        future: asyncio.Future[str],
    ) -> None:
        """Wait for agent response and update task state."""
        try:
            await asyncio.wait_for(future, timeout=300.0)
            logger.debug("A2A task {} completed", task_id)
        except asyncio.TimeoutError:
            logger.warning("A2A task {} timed out", task_id)
        except Exception as e:
            logger.error("A2A task {} failed: {}", task_id, e)
        finally:
            self._pending_tasks.pop(task_id, None)
            self._context_to_task.pop(context_id, None)

    async def on_get_task(
        self,
        params: TaskQueryParams,
        context: ServerCallContext | None = None,
    ) -> TaskType | None:
        """Handle tasks/get."""
        return None

    async def on_cancel_task(
        self,
        params: TaskIdParams,
        context: ServerCallContext | None = None,
    ) -> TaskType | None:
        """Handle tasks/cancel."""
        task_id = params.taskId
        if task_id in self._pending_tasks:
            future = self._pending_tasks[task_id]
            if not future.done():
                future.cancel()
            self._pending_tasks.pop(task_id, None)
        return None

    async def on_set_task_push_notification_config(
        self,
        params: TaskPushNotificationConfig,
        context: ServerCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        """Handle push notification config (not implemented)."""
        return params

    async def on_get_task_push_notification_config(
        self,
        params: GetTaskPushNotificationConfigParams,
        context: ServerCallContext | None = None,
    ) -> TaskPushNotificationConfig | None:
        """Handle get push notification config (not implemented)."""
        return None

    async def on_list_task_push_notification_config(
        self,
        params: ListTaskPushNotificationConfigParams,
        context: ServerCallContext | None = None,
    ) -> list[TaskPushNotificationConfig]:
        """Handle list push notification configs (not implemented)."""
        return []

    async def on_delete_task_push_notification_config(
        self,
        params: DeleteTaskPushNotificationConfigParams,
        context: ServerCallContext | None = None,
    ) -> None:
        """Handle delete push notification config (not implemented)."""
        pass

    async def on_resubscribe_to_task(
        self,
        params: TaskIdParams,
        context: ServerCallContext | None = None,
    ) -> AsyncGenerator[Any, None]:
        """Handle task resubscription (not implemented)."""
        yield None

    def _extract_content(self, message: Message | None) -> str:
        """Extract text from A2A Message parts."""
        if not message or not message.parts:
            return ""

        texts = []
        for part in message.parts:
            # Part is a RootModel wrapping TextPart/DataPart/etc. Access via .root
            inner = part.root if hasattr(part, 'root') else part
            if hasattr(inner, 'kind') and inner.kind == "text" and hasattr(inner, 'text'):
                texts.append(inner.text)
            elif hasattr(inner, 'kind') and inner.kind == "data" and hasattr(inner, 'data'):
                texts.append(json.dumps(inner.data))

        return "\n".join(texts)

    def deliver_response(self, task_id: str, content: str) -> bool:
        """Deliver agent response to a pending task."""
        if task_id in self._pending_tasks:
            future = self._pending_tasks[task_id]
            if not future.done():
                future.set_result(content)
                logger.debug("A2A response delivered to task {}", task_id)
                return True
        return False


class A2AChannel(BaseChannel):
    """
    A2A Protocol channel using the official a2a-sdk.

    Bridges A2A Tasks to Nanobot's message bus.
    """

    name = "a2a"

    def __init__(
        self,
        config: Any,
        bus: MessageBus,
        session_manager: Any = None,
    ):
        super().__init__(config, bus)
        self._session_manager = session_manager
        self._dispatch_task: asyncio.Task | None = None
        self._app: A2AStarletteApplication | None = None
        self._agent_card: AgentCardType | None = None
        self._handler: A2ARequestHandler | None = None

        if not A2A_AVAILABLE:
            logger.warning("a2a-sdk not installed, A2A channel will not function")
            return

        # Convert skill dicts to AgentSkill objects
        skill_dicts = getattr(config, "skills", [])
        skills = []
        for skill_data in skill_dicts:
            if isinstance(skill_data, dict):
                skills.append(AgentSkill(
                    id=skill_data.get("id", "skill"),
                    name=skill_data.get("name", "Skill"),
                    description=skill_data.get("description", ""),
                    tags=skill_data.get("tags", []),
                ))

        self._agent_card = AgentCardType(
            name=getattr(config, "agent_name", "Nanobot"),
            url=getattr(config, "agent_url", "http://localhost:8000"),
            description=getattr(config, "agent_description", "Nanobot AI Agent"),
            version="1.0.0",
            capabilities={"streaming": True, "pushNotifications": False},
            skills=skills,
            defaultInputModes=["text/plain"],
            defaultOutputModes=["text/plain"],
            supportsAuthenticatedExtendedCard=False,
        )

        self._handler = A2ARequestHandler(self)
        self._app = A2AStarletteApplication(
            agent_card=self._agent_card,
            http_handler=self._handler,
        )

    async def start(self) -> None:
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_responses())
        logger.info("A2A channel started")

    async def stop(self) -> None:
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        logger.info("A2A channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        if not self._handler:
            return

        task_id = msg.metadata.get("task_id") if msg.metadata else None

        if not task_id:
            context_id = msg.chat_id
            task_id = self._handler._context_to_task.get(context_id)

        if task_id:
            self._handler.deliver_response(task_id, msg.content)

    async def _dispatch_responses(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
                if msg.channel == "a2a":
                    await self.send(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("A2A dispatch error: {}", e)

    def get_asgi_app(self):
        if self._app:
            return self._app.build()
        raise RuntimeError("A2A server not initialized")

    @property
    def agent_card(self) -> AgentCard | None:
        return self._agent_card
