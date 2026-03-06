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
        TextPart,
        TaskStatusUpdateEvent,
        TaskArtifactUpdateEvent,
    )

    A2A_AVAILABLE = True
except ImportError:
    A2A_AVAILABLE = False
    A2AStarletteApplication = None
    RequestHandler = object
    TaskStatusUpdateEvent = None
    TaskArtifactUpdateEvent = None
    AgentCardType = None
    AgentSkill = None
    ServerCallContext = None
    Artifact = None
    InMemoryTaskStore = None


ID_LENGTH = 12
PROGRESS_MIN_INTERVAL_SECONDS = 0.5


class A2ARequestHandler(RequestHandler):
    """A2A request handler that bridges to Nanobot's message bus."""

    DEFAULT_TASK_TTL_SECONDS = 1209600  # 14 days

    def __init__(
        self,
        channel: "A2AChannel",
        task_retention_seconds: float = DEFAULT_TASK_TTL_SECONDS,
        provider: Any = None,
        model: str | None = None,
        summarize_progress: bool = True,
    ):
        self._channel = channel
        self._task_store = InMemoryTaskStore()
        self._context_to_task: dict[str, str] = {}
        self._task_to_context: dict[str, str] = {}
        self._completed_tasks: dict[str, float] = {}
        self._context_lock = asyncio.Lock()
        self._task_ttl = task_retention_seconds
        self._task_queues: dict[str, list[asyncio.Queue]] = {}
        self._provider = provider
        self._model = model
        self._summarize_progress = summarize_progress
        self._last_progress_time: dict[str, float] = {}

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
        self._task_to_context[task_id] = context_id

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
        """Handle message/send streaming via SSE.

        Creates a task, publishes to the bus, then yields status updates
        as they arrive on the task's queue until completion.
        """
        task = await self.on_message_send(params, context)

        queue = asyncio.Queue()
        if task.id not in self._task_queues:
            self._task_queues[task.id] = []
        self._task_queues[task.id].append(queue)

        yield TaskStatusUpdateEvent(
            taskId=task.id,
            contextId=task.context_id or "",
            status=TaskStatus(state=TaskState.working),
            final=False,
        )

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if task.id in self._task_queues:
                self._task_queues[task.id] = [
                    q for q in self._task_queues[task.id] if q is not queue
                ]
                if not self._task_queues[task.id]:
                    del self._task_queues[task.id]

    async def deliver_progress(self, task_id: str, raw_text: str) -> bool:
        """Deliver a progress message to streaming clients.

        If summarize_progress is enabled and a provider is configured,
        uses the LLM to summarize the raw progress text into 1 sentence.
        Then pushes a TaskStatusUpdateEvent to all queues for this task.
        """
        if task_id not in self._task_queues:
            return False

        now = time.time()
        if now - self._last_progress_time.get(task_id, 0) < PROGRESS_MIN_INTERVAL_SECONDS:
            return False
        self._last_progress_time[task_id] = now

        summary = raw_text
        if self._summarize_progress and self._provider and self._model:
            try:
                response = await self._provider.chat(
                    messages=[
                        {
                            "role": "user",
                            "content": f"Summarize this agent status update in one concise sentence for an API client:\n\n{raw_text}",
                        }
                    ],
                    tools=[],
                    model=self._model,
                    temperature=0.3,
                    max_tokens=256,
                    reasoning_effort=None,
                )
                summary = response.content[0].text.strip() if response.content else raw_text[:120]
            except Exception as e:
                logger.warning("Failed to summarize progress: {}", e)
                summary = raw_text[:120]

        status_message = Message(
            message_id=uuid.uuid4().hex[:ID_LENGTH],
            role="agent",
            parts=[Part(root=TextPart(kind="text", text=summary))],
        )
        status_event = TaskStatusUpdateEvent(
            taskId=task_id,
            contextId=self._task_to_context.get(task_id, ""),
            status=TaskStatus(state=TaskState.working, message=status_message),
            final=False,
        )

        for queue in self._task_queues.get(task_id, []):
            queue.put_nowait(status_event)

        return True

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
            if task.id in self._task_queues:
                for queue in self._task_queues[task.id]:
                    queue.put_nowait(None)
                del self._task_queues[task.id]
            self._last_progress_time.pop(task.id, None)
            if task.context_id and task.context_id in self._context_to_task:
                del self._context_to_task[task.context_id]
            self._task_to_context.pop(task.id, None)
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
        """Handle task resubscription - reconnect to a task's stream.

        If the task is still in-progress, connects to the live queue.
        If already completed, replays the final events from the store.
        """
        task_id = params.id
        task = await self._task_store.get(task_id)

        if not task:
            yield None
            return

        if task.status.state == TaskState.completed:
            if task.artifacts:
                yield TaskArtifactUpdateEvent(
                    taskId=task_id,
                    contextId=task.context_id or "",
                    artifact=task.artifacts[0],
                    lastChunk=True,
                )
            yield TaskStatusUpdateEvent(
                taskId=task_id,
                contextId=task.context_id or "",
                status=TaskStatus(state=TaskState.completed),
                final=True,
            )
            return

        yield TaskStatusUpdateEvent(
            taskId=task_id,
            contextId=task.context_id or "",
            status=TaskStatus(state=TaskState.working),
            final=False,
        )

        queue = asyncio.Queue()
        if task_id not in self._task_queues:
            self._task_queues[task_id] = []
        self._task_queues[task_id].append(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if task_id in self._task_queues:
                self._task_queues[task_id] = [
                    q for q in self._task_queues[task_id] if q is not queue
                ]
                if not self._task_queues[task_id]:
                    del self._task_queues[task_id]

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

    async def _cleanup_completed_tasks(self) -> None:
        """Remove completed tasks tracking that have exceeded TTL.

        Note: This cleans up our tracking dicts but relies on InMemoryTaskStore
        having a delete method (if available) to actually remove tasks from the store.
        """
        now = time.time()
        expired = [
            task_id
            for task_id, completed_at in self._completed_tasks.items()
            if now - completed_at > self._task_ttl
        ]
        for task_id in expired:
            del self._completed_tasks[task_id]
            delete_fn = getattr(self._task_store, "delete", None)
            if delete_fn:
                try:
                    # Guard against future async delete implementations
                    if asyncio.iscoroutinefunction(delete_fn):
                        await delete_fn(task_id)
                    else:
                        delete_fn(task_id)
                except Exception:
                    pass

    async def deliver_response(self, task_id: str, content: str) -> bool:
        """Deliver agent response to a pending task.

        Also pushes artifact and completion events to any streaming queues.
        """
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

            if task.id in self._task_queues:
                artifact_event = TaskArtifactUpdateEvent(
                    taskId=task_id,
                    contextId=task.context_id or "",
                    artifact=task.artifacts[0],
                    lastChunk=True,
                )
                status_event = TaskStatusUpdateEvent(
                    taskId=task_id,
                    contextId=task.context_id or "",
                    status=TaskStatus(state=TaskState.completed),
                    final=True,
                )
                for queue in self._task_queues.get(task_id, []):
                    queue.put_nowait(artifact_event)
                    queue.put_nowait(status_event)
                    queue.put_nowait(None)

            if task.context_id and task.context_id in self._context_to_task:
                del self._context_to_task[task.context_id]
            self._task_to_context.pop(task.id, None)
            self._last_progress_time.pop(task.id, None)
            self._completed_tasks[task_id] = time.time()
            await self._cleanup_completed_tasks()
            logger.debug("A2A response delivered to task {}", task_id)
            return True
        return False


class A2AChannel(BaseChannel):
    """
    A2A Protocol channel using the official a2a-sdk.

    Bridges A2A Tasks to Nanobot's message bus.

    Security note: By default, only the running_user is allowed to access the A2A endpoint.
    For production, deploy behind an authenticating proxy and configure allow_from appropriately.
    """

    name = "a2a"

    def __init__(
        self,
        config: A2AChannelConfig,
        bus: MessageBus,
        display_name: str = "nanobot",
        provider: Any = None,
        model: str | None = None,
    ):
        super().__init__(config, bus)
        self.config = config

        # Get running user (default to current OS user)
        import getpass

        self._running_user = getattr(config, "running_user", "") or getpass.getuser()

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
            name=(config.agent_name or "").strip() or display_name.strip() or "nanobot",
            url=getattr(config, "agent_url", "http://localhost:8000"),
            description=getattr(config, "agent_description", "Nanobot AI Agent"),
            version="1.0.0",
            capabilities={"streaming": True, "pushNotifications": False},
            skills=skills,
            defaultInputModes=["text/plain"],
            defaultOutputModes=["text/plain"],
            supportsAuthenticatedExtendedCard=False,
        )

        # Get task retention from config (days → seconds)
        retention_days = getattr(config, "task_retention_days", 14.0)
        retention_seconds = retention_days * 86400
        self._handler = A2ARequestHandler(
            self,
            task_retention_seconds=retention_seconds,
            provider=provider,
            model=model,
            summarize_progress=getattr(config, "summarize_progress", True),
        )

        self._app = A2AStarletteApplication(
            agent_card=self._agent_card,
            http_handler=self._handler,
        )

    def is_allowed(self, sender_id: str) -> bool:
        """
        Check if a sender is allowed to use this A2A endpoint.

        Authorization logic:
        - If allow_from is non-empty, check against that list
        - If allow_from is empty, only allow the running_user

        Args:
            sender_id: The sender's identifier (from message.role.value).

        Returns:
            True if allowed, False otherwise.
        """
        allow_list = getattr(self.config, "allow_from", [])

        # If allow_from is configured, use it
        if allow_list:
            return sender_id in allow_list

        # Default: only allow running_user
        return sender_id == self._running_user

    async def start(self) -> None:
        self._running = True
        logger.info("A2A channel started")

    async def stop(self) -> None:
        self._running = False
        logger.info("A2A channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        if not self._handler:
            return

        if msg.metadata and msg.metadata.get("_progress"):
            task_id = msg.metadata.get("task_id")
            if not task_id:
                task_id = self._handler._context_to_task.get(msg.chat_id)
            if task_id:
                try:
                    await self._handler.deliver_progress(task_id, msg.content)
                except Exception as e:
                    logger.error("A2A progress error: {}", e)
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
