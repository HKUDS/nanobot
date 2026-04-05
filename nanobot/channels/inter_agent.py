"""Inter-agent communication channel.

Enables direct HTTP-based communication between nanobot instances, allowing
multiple agents to collaborate autonomously on tasks without human mediation.

Design: Async Task Model
------------------------
Unlike a simple synchronous request/response, this channel uses an async task
model so the initiating instance is never blocked waiting for a peer to finish.

Flow:
  1. POST /inter-agent/chat  → submit task, get task_id immediately (202)
  2. GET  /inter-agent/task/{task_id}  → poll for status + result
  3. When status == "done", result contains the agent's response

This means:
  - The initiating agent submits a task and moves on (no blocking)
  - The receiving agent processes at its own pace, regardless of queue depth
  - The initiator polls until done, with full visibility into task state
  - No silent result loss: a task is either pending/running/done/failed

API
---
POST /inter-agent/chat
    {"message": "...", "session_id": "collab_abc", "from_instance": "alice", "round_count": 1}
    → 202 {"task_id": "...", "status": "pending", "instance": "bob"}

GET /inter-agent/task/{task_id}
    → {"task_id": "...", "status": "pending|running|done|failed",
       "response": "...",      # present when status == "done"
       "is_final": false,      # present when status == "done"
       "error": "...",         # present when status == "failed"
       "instance": "bob", "session_id": "collab_abc"}

GET /inter-agent/health
    → {"status": "ok", "instance": "bob", "port": 18801}

Configuration (config.json)
----------------------------
{
  "channels": {
    "interagent": {
      "enabled": true,
      "apiPort": 18801,
      "instanceName": "bob",
      "auditWebhookUrl": "https://...",
      "maxRoundsPerSession": 30,
      "taskTtlSeconds": 3600
    }
  }
}

Polling pattern (in AGENTS.md / skill)
---------------------------------------
import httpx, time

def submit(url, message, session_id, from_instance, round_count):
    r = httpx.post(f"{url}/inter-agent/chat", json={
        "message": message, "session_id": session_id,
        "from_instance": from_instance, "round_count": round_count,
    }, timeout=10)
    return r.json()["task_id"]

def poll(url, task_id, interval=3, max_wait=600):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        r = httpx.get(f"{url}/inter-agent/task/{task_id}", timeout=10)
        data = r.json()
        if data["status"] in ("done", "failed"):
            return data
        time.sleep(interval)
    raise TimeoutError(f"task {task_id} not done after {max_wait}s")
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import aiohttp.web
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class InterAgentConfig(Base):
    """Configuration for the inter-agent communication channel."""

    enabled: bool = False
    api_port: int = 18800
    instance_name: str = ""
    audit_webhook_url: str = ""
    max_rounds_per_session: int = 30
    task_ttl_seconds: int = 3600  # how long to keep completed tasks in memory


# ---------------------------------------------------------------------------
# Task registry
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING = "pending"    # queued, agent hasn't started yet
    RUNNING = "running"    # agent is processing
    DONE    = "done"       # agent replied successfully
    FAILED  = "failed"     # agent loop error or explicit failure


@dataclass
class AgentTask:
    task_id: str
    session_id: str
    from_instance: str
    round_count: int
    status: TaskStatus = TaskStatus.PENDING
    response: str | None = None
    is_final: bool = False
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self, instance_name: str) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "status": self.status.value,
            "instance": instance_name,
            "session_id": self.session_id,
            "round_count": self.round_count,
        }
        if self.status == TaskStatus.DONE:
            d["response"] = self.response
            d["is_final"] = self.is_final
        if self.status == TaskStatus.FAILED:
            d["error"] = self.error
        return d


# task_id → AgentTask
_tasks: dict[str, AgentTask] = {}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHUNK = 3800  # safe chunk size under Feishu's 4096-char webhook limit

_FINAL_SIGNALS = [
    "最终方案", "讨论结束", "达成共识", "已确认",
    "final proposal", "discussion complete", "consensus reached",
    "DISCUSSION_COMPLETE",
]


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class InterAgentChannel(BaseChannel):
    """HTTP API channel for real-time inter-agent communication (async task model)."""

    name = "interagent"
    display_name = "Inter-Agent"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return InterAgentConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = InterAgentConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: InterAgentConfig = config
        self._runner: aiohttp.web.AppRunner | None = None

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        app = aiohttp.web.Application()
        app.router.add_get("/inter-agent/health",         self._handle_health)
        app.router.add_post("/inter-agent/chat",          self._handle_chat)
        app.router.add_get("/inter-agent/task/{task_id}", self._handle_task_status)

        self._runner = aiohttp.web.AppRunner(app)
        await self._runner.setup()
        site = aiohttp.web.TCPSite(self._runner, "0.0.0.0", self.config.api_port)
        await site.start()
        logger.info(
            "Inter-agent API listening on port {} (instance: {})",
            self.config.api_port,
            self.config.instance_name,
        )
        try:
            while self._running:
                await asyncio.sleep(60)
                self._evict_old_tasks()
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._running = False
        if self._runner:
            await self._runner.cleanup()

    async def send(self, msg: OutboundMessage) -> None:
        """Called by the agent loop when a response is ready. Marks the task done."""
        task = _tasks.get(msg.chat_id)
        if task is None:
            logger.warning("Inter-agent: send() called for unknown task_id={}", msg.chat_id)
            return
        task.status = TaskStatus.DONE
        task.response = msg.content
        task.is_final = _is_final(msg.content)
        task.finished_at = time.time()
        logger.info("Inter-agent task {} done (session={})", msg.chat_id, task.session_id)

        asyncio.create_task(self._push_audit(
            self.config.instance_name, task.from_instance,
            task.session_id, task.round_count, msg.content,
        ))

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    async def _handle_health(self, _request: aiohttp.web.Request) -> aiohttp.web.Response:
        return aiohttp.web.json_response({
            "status": "ok",
            "instance": self.config.instance_name,
            "port": self.config.api_port,
        })

    async def _handle_chat(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """Submit a task. Returns 202 immediately with task_id."""
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return aiohttp.web.json_response({"error": "invalid JSON"}, status=400)

        message: str = body.get("message", "").strip()
        session_id: str = body.get("session_id", "")
        from_instance: str = body.get("from_instance", "unknown")
        round_count: int = int(body.get("round_count", 0))

        if not message or not session_id:
            return aiohttp.web.json_response(
                {"error": "message and session_id are required"}, status=400
            )

        task_id = str(uuid.uuid4())
        task = AgentTask(
            task_id=task_id,
            session_id=session_id,
            from_instance=from_instance,
            round_count=round_count,
        )
        _tasks[task_id] = task

        logger.info(
            "Inter-agent task {} created | from={} session={} round={}",
            task_id, from_instance, session_id, round_count,
        )

        # Audit: inbound
        asyncio.create_task(self._push_audit(
            from_instance, self.config.instance_name, session_id, round_count, message
        ))

        # Inject into agent loop.
        # - chat_id = task_id  → send() can look up the task in _tasks
        # - session_key_override = interagent:{task_id}  → each task gets its own
        #   session key so tasks within the same logical session don't block each other
        #   via the global _processing_lock. Conversation history is still scoped to
        #   the task (not shared across rounds), which is correct for stateless calls.
        await self.bus.publish_inbound(InboundMessage(
            channel=self.name,
            sender_id=from_instance,
            chat_id=task_id,
            content=message,
            metadata={"from_instance": from_instance, "round_count": round_count, "session_id": session_id},
            session_key_override=f"interagent:{task_id}",
        ))

        task.status = TaskStatus.RUNNING

        return aiohttp.web.json_response(
            task.to_dict(self.config.instance_name), status=202
        )

    async def _handle_task_status(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """Poll task status and result."""
        task_id: str = request.match_info["task_id"]
        task = _tasks.get(task_id)
        if task is None:
            return aiohttp.web.json_response({"error": "task not found"}, status=404)
        return aiohttp.web.json_response(task.to_dict(self.config.instance_name))

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def _evict_old_tasks(self) -> None:
        """Remove completed tasks older than task_ttl_seconds."""
        cutoff = time.time() - self.config.task_ttl_seconds
        to_delete = [
            tid for tid, t in _tasks.items()
            if t.status in (TaskStatus.DONE, TaskStatus.FAILED)
            and t.finished_at is not None
            and t.finished_at < cutoff
        ]
        for tid in to_delete:
            del _tasks[tid]
        if to_delete:
            logger.debug("Inter-agent: evicted {} expired tasks", len(to_delete))

    # ------------------------------------------------------------------
    # Audit webhook
    # ------------------------------------------------------------------

    async def _push_audit(
        self,
        from_instance: str,
        to_instance: str,
        session_id: str,
        round_count: int,
        message: str,
    ) -> None:
        """Push message to audit webhook, chunking if needed."""
        url = self.config.audit_webhook_url
        if not url:
            return

        header = (
            f"【实例间对话】\n"
            f"{from_instance} → {to_instance}\n"
            f"Session: {session_id}  轮次: {round_count}\n\n"
        )
        chunks = [message[i:i + _CHUNK] for i in range(0, max(len(message), 1), _CHUNK)]
        total = len(chunks)

        try:
            async with aiohttp.ClientSession() as http:
                for idx, chunk in enumerate(chunks):
                    page = f"（{idx + 1}/{total}）\n" if total > 1 else ""
                    payload = {"msg_type": "text", "content": {"text": header + page + chunk}}
                    await http.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10))
        except Exception as exc:
            logger.warning("Inter-agent audit webhook failed: {}", exc)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _is_final(text: str) -> bool:
    """Return True when the response signals that the discussion is concluded."""
    lower = text.lower()
    return any(sig.lower() in lower for sig in _FINAL_SIGNALS)
