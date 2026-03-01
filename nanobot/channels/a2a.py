"""A2A Protocol channel using official a2a-sdk."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import A2AChannelConfig

if TYPE_CHECKING:
    from a2a.types import AgentCard as AgentCardType, Task as TaskType

try:
    from a2a.server.apps.jsonrpc.starlette_app import A2AStarletteApplication
    from a2a.server.request_handlers.request_handler import RequestHandler
    from a2a.server.context import ServerCallContext
    from a2a.server.tasks import InMemoryTaskStore
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
        Artifact,
    )

    A2A_AVAILABLE = True
except ImportError:
    A2A_AVAILABLE = False
    A2AStarletteApplication = None
    RequestHandler = object
    AgentCardType = None
    AgentSkill = None
    ServerCallContext = None
    Artifact = None
    InMemoryTaskStore = None


ID_LENGTH = 12


class A2ARequestHandler(RequestHandler):
    """A2A request handler that bridges to Nanobot's message bus."""

    COMPLETED_TASK_TTL_SECONDS = 86400  # 24 hours

    def __init__(self, channel: "A2AChannel"):
        self._channel = channel
        self._task_store = InMemoryTaskStore()
        self._context_to_task: dict[str, str] = {}
        self._completed_tasks: dict[str, float] = {}
        self._context_lock = asyncio.Lock()

    async def on_message_send(
        self,
        params: MessageSendParams,
        context: ServerCallContext | None = None,
    ) -> TaskType:
        """Handle message/send - create task and route to bus.

        Authorization note: sender_id is derived from message.role.value which is
        client-controlled. ServerCallContext does not provide authenticated identity.
        For stronger auth, deploy behind an authenticating proxy.
        """
        if not A2A_AVAILABLE:
            raise RuntimeError("a2a-sdk not installed")

        message = params.message

        sender_id = message.role.value if message else "a2a-client"

        if not self._channel.is_allowed(sender_id):
            logger.warning("A2A request from unauthorized sender: {}", sender_id)
            raise PermissionError(f"Sender '{sender_id}' not authorized")

        async with self._context_lock:
            if message and message.context_id:
                context_id = message.context_id
            else:
                context_id = f"a2a:{uuid.uuid4().hex[:ID_LENGTH]}"

            content = self._extract_content(message)
            task_id = uuid.uuid4().hex[:ID_LENGTH]

        task = TaskType(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.working),
        )
        await self._task_store.save(task)
        self._context_to_task[context_id] = task_id

        inbound = InboundMessage(
            channel="a2a",
            sender_id=sender_id,
            chat_id=context_id,
            content=content,
            metadata={"task_id": task_id, "a2a_context_id": context_id},
            session_key_override=context_id,
        )

        try:
            await self._channel.bus.publish_inbound(inbound)
            logger.debug("A2A task {} published to bus", task_id)
        except Exception:
            del self._context_to_task[context_id]
            raise

        return task

    async def on_message_send_stream(
        self,
        params: MessageSendParams,
        context: ServerCallContext | None = None,
    ) -> AsyncGenerator[Any, None]:
        """Handle message/send streaming - delegates to non-streaming for now."""
        task = await self.on_message_send(params, context)
        yield task

    async def on_get_task(
        self,
        params: TaskQueryParams,
        context: ServerCallContext | None = None,
    ) -> TaskType | None:
        """Handle tasks/get - return task status."""
        return await self._task_store.get(params.id)

    async def on_cancel_task(
        self,
        params: TaskIdParams,
        context: ServerCallContext | None = None,
    ) -> TaskType | None:
        """Handle tasks/cancel."""
        task = await self._task_store.get(params.id)
        if task:
            task.status = TaskStatus(state=TaskState.canceled)
            await self._task_store.save(task)
            if task.context_id and task.context_id in self._context_to_task:
                del self._context_to_task[task.context_id]
            return task
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
            inner = part.root if hasattr(part, "root") else part
            if hasattr(inner, "kind") and inner.kind == "text" and hasattr(inner, "text"):
                texts.append(inner.text)
            elif hasattr(inner, "kind") and inner.kind == "data" and hasattr(inner, "data"):
                texts.append(json.dumps(inner.data))

        return "\n".join(texts)

    def _cleanup_completed_tasks(self) -> None:
        """Remove completed tasks tracking that have exceeded TTL.

        Note: This cleans up our tracking dicts but relies on InMemoryTaskStore
        having a delete method (if available) to actually remove tasks from the store.
        """
        now = time.time()
        expired = [
            task_id
            for task_id, completed_at in self._completed_tasks.items()
            if now - completed_at > self.COMPLETED_TASK_TTL_SECONDS
        ]
        for task_id in expired:
            del self._completed_tasks[task_id]
            delete_fn = getattr(self._task_store, "delete", None)
            if delete_fn:
                try:
                    delete_fn(task_id)
                except Exception:
                    pass

    async def deliver_response(self, task_id: str, content: str) -> bool:
        """Deliver agent response to a pending task."""
        task = await self._task_store.get(task_id)
        if task:
            task.status = TaskStatus(state=TaskState.completed)
            task.artifacts = [
                Artifact(
                    artifact_id="0",
                    parts=[Part(type="text", text=content)],
                )
            ]
            await self._task_store.save(task)
            if task.context_id and task.context_id in self._context_to_task:
                del self._context_to_task[task.context_id]
            self._completed_tasks[task_id] = time.time()
            self._cleanup_completed_tasks()
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
        config: A2AChannelConfig,
        bus: MessageBus,
    ):
        super().__init__(config, bus)
        self.config = config
        self._app: A2AStarletteApplication | None = None
        self._agent_card: AgentCardType | None = None
        self._handler: A2ARequestHandler | None = None

        if not A2A_AVAILABLE:
            logger.warning("a2a-sdk not installed, A2A channel will not function")
            return

        skill_dicts = getattr(config, "skills", [])
        skills = []
        for skill_data in skill_dicts:
            if isinstance(skill_data, dict):
                skills.append(
                    AgentSkill(
                        id=skill_data.get("id", "skill"),
                        name=skill_data.get("name", "Skill"),
                        description=skill_data.get("description", ""),
                        tags=skill_data.get("tags", []),
                    )
                )

        self._agent_card = AgentCardType(
            name=getattr(config, "agent_name", "Nanobot"),
            url=getattr(config, "agent_url", "http://localhost:8000"),
            description=getattr(config, "agent_description", "Nanobot AI Agent"),
            version="1.0.0",
            capabilities={"streaming": False, "pushNotifications": False},
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
        logger.info("A2A channel started")

    async def stop(self) -> None:
        self._running = False
        logger.info("A2A channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        if not self._handler:
            return

        task_id = msg.metadata.get("task_id") if msg.metadata else None

        if not task_id:
            context_id = msg.chat_id
            task_id = self._handler._context_to_task.get(context_id)

        if task_id:
            try:
                await self._handler.deliver_response(task_id, msg.content)
            except Exception as e:
                logger.error("A2A send error: {}", e)
                raise

    def get_asgi_app(self):
        if self._app:
            return self._app.build()
        raise RuntimeError("A2A server not initialized")

    @property
    def agent_card(self) -> AgentCardType | None:
        return self._agent_card
