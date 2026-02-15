"""Job tracking system for monitoring agent execution with visual progress."""

import asyncio
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists."""
    path.mkdir(parents=True, exist_ok=True)
    return path


class ToolCallStatus(Enum):
    """Status of a tool call."""

    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"  # For rate limit retries
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    THINKING = "thinking"  # For LLM thinking/reasoning


@dataclass
class ToolCallRecord:
    """Record of a single tool call."""

    id: str
    name: str
    arguments: dict[str, Any]
    status: ToolCallStatus
    result: str = ""
    error: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    @property
    def duration_ms(self) -> int:
        """Get duration in milliseconds."""
        if self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return 0

    def to_emoji(self) -> str:
        """Convert status to emoji."""
        # Special case for thinking tool
        if self.name == "🧠 thinking" or self.name == "thinking":
            return "🧠"
        # Special case for memory consolidation
        if self.name == "memory_consolidation":
            return "🗄️"
        return {
            ToolCallStatus.PENDING: "⬜",
            ToolCallStatus.RUNNING: "🟧",
            ToolCallStatus.RETRYING: "🟨",  # Yellow for retry
            ToolCallStatus.SUCCESS: "🟩",
            ToolCallStatus.ERROR: "🟥",
            ToolCallStatus.SKIPPED: "⬛",
            ToolCallStatus.THINKING: "🧠",
        }.get(self.status, "⬜")


@dataclass
class Job:
    """A job representing a single user request and its execution."""

    id: str
    session_key: str
    channel: str
    chat_id: str
    user_message: str
    status: str = "pending"  # pending, running, completed, error, aborted
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    final_response: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    message_id: str | None = None  # Telegram message ID for editing
    aborted: bool = False  # Flag to request job abortion

    def request_abort(self) -> None:
        """Request this job to be aborted."""
        self.aborted = True
        self.status = "aborted"

    @property
    def is_aborted(self) -> bool:
        """Check if job has been aborted."""
        return self.aborted

    @property
    def duration_seconds(self) -> float:
        """Get total duration in seconds."""
        end = self.completed_at or datetime.now()
        return (end - self.created_at).total_seconds()

    def get_timeline_emoji(self, per_line: int = 10) -> str:
        """Generate emoji timeline of tool calls, broken into multiple lines."""
        emojis = [tc.to_emoji() for tc in self.tool_calls]
        if not emojis:
            return "⏳"

        # Break into lines
        lines = []
        for i in range(0, len(emojis), per_line):
            chunk = emojis[i : i + per_line]
            lines.append("".join(chunk))

        return "\n".join(lines)

    def get_summary(self) -> str:
        """Get a brief summary of the job."""
        total = len(self.tool_calls)
        success = sum(1 for tc in self.tool_calls if tc.status == ToolCallStatus.SUCCESS)
        error = sum(1 for tc in self.tool_calls if tc.status == ToolCallStatus.ERROR)
        running = sum(1 for tc in self.tool_calls if tc.status == ToolCallStatus.RUNNING)

        if self.status == "completed":
            return f"✅ Completed in {self.duration_seconds:.1f}s | {success} tools used"
        elif self.status == "error":
            return f"❌ Failed | {error} errors"
        else:
            return f"⏳ Running... | {running} active, {success} done"

    def add_tool_call(self, name: str, arguments: dict[str, Any], tool_id: str | None = None) -> ToolCallRecord:
        """Add a new pending tool call."""
        record = ToolCallRecord(
            id=tool_id or str(uuid.uuid4())[:8],
            name=name,
            arguments=arguments,
            status=ToolCallStatus.PENDING,
        )
        self.tool_calls.append(record)
        return record

    def update_tool_call(
        self, tool_id: str, status: ToolCallStatus, result: str = "", error: str = ""
    ) -> None:
        """Update a tool call status."""
        for tc in self.tool_calls:
            if tc.id == tool_id:
                tc.status = status
                tc.result = result
                tc.error = error
                if status in [ToolCallStatus.SUCCESS, ToolCallStatus.ERROR]:
                    tc.completed_at = datetime.now()
                break


class JobManager:
    """Manages jobs - keeps last 10 jobs per session with persistence."""

    MAX_JOBS_PER_SESSION = 10

    def __init__(self, workspace: Path | None = None):
        self._jobs: dict[str, list[Job]] = {}  # session_key -> list of Jobs (oldest first)
        self._lock = asyncio.Lock()
        # Persistence file in workspace or home directory
        if workspace:
            self._persist_dir = ensure_dir(workspace / ".nanobot")
        else:
            self._persist_dir = ensure_dir(Path.home() / ".nanobot")
        self._persist_file = self._persist_dir / "jobs.json"

    def _job_to_dict(self, job: Job) -> dict:
        """Convert Job to dictionary for serialization."""
        return {
            "id": job.id,
            "session_key": job.session_key,
            "channel": job.channel,
            "chat_id": job.chat_id,
            "user_message": job.user_message,
            "status": job.status,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "message_id": job.message_id,
            "final_response": job.final_response,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "status": tc.status.value,
                    "result": tc.result,
                    "error": tc.error,
                    "started_at": tc.started_at.isoformat() if tc.started_at else None,
                    "completed_at": tc.completed_at.isoformat() if tc.completed_at else None,
                }
                for tc in job.tool_calls
            ],
        }

    def _dict_to_job(self, data: dict) -> Job:
        """Convert dictionary back to Job."""
        job = Job(
            id=data["id"],
            session_key=data["session_key"],
            channel=data["channel"],
            chat_id=data["chat_id"],
            user_message=data["user_message"],
            status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            message_id=data.get("message_id"),
            final_response=data.get("final_response") or "",
        )
        # Restore tool calls
        for tc_data in data.get("tool_calls", []):
            tc = ToolCallRecord(
                id=tc_data["id"],
                name=tc_data["name"],
                arguments=tc_data.get("arguments", {}),
                status=ToolCallStatus(tc_data["status"]),
                result=tc_data.get("result", ""),
                error=tc_data.get("error", ""),
                started_at=datetime.fromisoformat(tc_data["started_at"]) if tc_data.get("started_at") else datetime.now(),
                completed_at=datetime.fromisoformat(tc_data["completed_at"]) if tc_data.get("completed_at") else None,
            )
            job.tool_calls.append(tc)
        return job

    async def _save(self) -> None:
        """Save jobs to disk."""
        try:
            # Ensure directory exists
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            
            data = {
                session_key: [self._job_to_dict(job) for job in jobs]
                for session_key, jobs in self._jobs.items()
            }
            self._persist_file.write_text(json.dumps(data, indent=2))
            logger.debug(f"Saved {sum(len(jobs) for jobs in self._jobs.values())} jobs to {self._persist_file}")
        except Exception as e:
            logger.error(f"Failed to save jobs: {e}")

    async def load(self) -> list[Job]:
        """Load jobs from disk and return incomplete jobs."""
        if not self._persist_file.exists():
            logger.debug("No persisted jobs file found")
            return []

        try:
            data = json.loads(self._persist_file.read_text())
            incomplete_jobs = []

            for session_key, jobs_data in data.items():
                self._jobs[session_key] = []
                for job_data in jobs_data:
                    job = self._dict_to_job(job_data)
                    self._jobs[session_key].append(job)
                    # Check if job was incomplete
                    if job.status in ["running", "pending"]:
                        incomplete_jobs.append(job)

            total = sum(len(jobs) for jobs in self._jobs.values())
            logger.info(f"Loaded {total} jobs from {self._persist_file}, {len(incomplete_jobs)} incomplete")
            return incomplete_jobs
        except Exception as e:
            logger.error(f"Failed to load jobs: {e}")
            return []

    async def handle_interrupted_jobs(self, bus) -> None:
        """Restart incomplete jobs automatically."""
        incomplete = await self.load()
        if not incomplete:
            return

        from nanobot.bus.events import InboundMessage, OutboundMessage

        for job in incomplete:
            logger.info(f"Auto-restarting interrupted job {job.id}: {job.user_message[:50]}...")
            
            # Notify user that job is restarting
            if job.channel and job.chat_id:
                try:
                    await bus.publish_outbound(OutboundMessage(
                        channel=job.channel,
                        chat_id=job.chat_id,
                        content=f"🔄 Restarting interrupted job...\n\nJob ID: `{job.id}`\nMessage: {job.user_message[:100]}..."
                    ))
                except Exception as e:
                    logger.error(f"Failed to notify about job restart {job.id}: {e}")
            
            # Reset job status to running for restart
            async with self._lock:
                job.status = "running"
                job.completed_at = None
                job.final_response = ""
            await self._save()
            
            # Re-create the inbound message from job data
            try:
                msg = InboundMessage(
                    channel=job.channel,
                    sender_id=job.session_key.split(":")[1] if ":" in job.session_key else job.chat_id,
                    chat_id=job.chat_id,
                    content=job.user_message,
                    metadata={
                        "job_id": job.id,
                        "is_restart": True,
                        "original_job_id": job.id,
                    }
                )
                
                # Publish to bus for processing
                await bus.publish_inbound(msg)
                logger.info(f"Re-queued job {job.id} for processing")
                
            except Exception as e:
                logger.error(f"Failed to restart job {job.id}: {e}")
                # Mark as failed if we can't restart
                await self.fail_job(job.id, f"Failed to restart: {e}")

    async def create_job(
        self,
        session_key: str,
        channel: str,
        chat_id: str,
        user_message: str,
    ) -> Job:
        """Create a new job, adding to the session's job history."""
        async with self._lock:
            job = Job(
                id=str(uuid.uuid4())[:12],
                session_key=session_key,
                channel=channel,
                chat_id=chat_id,
                user_message=user_message[:200],
                status="running",
            )
            # Add to session's job list
            if session_key not in self._jobs:
                self._jobs[session_key] = []
            self._jobs[session_key].append(job)
            # Keep only last N jobs
            if len(self._jobs[session_key]) > self.MAX_JOBS_PER_SESSION:
                self._jobs[session_key] = self._jobs[session_key][-self.MAX_JOBS_PER_SESSION :]
            logger.info(
                f"Created job {job.id} for session {session_key} (total: {len(self._jobs[session_key])})"
            )
            # Persist jobs after creation
            await self._save()
            return job

    async def get_job(self, job_id: str) -> Job | None:
        """Get a job by ID - searches all jobs in all sessions."""
        for jobs in self._jobs.values():
            for job in jobs:
                if job.id == job_id:
                    return job
        return None

    async def get_last_job(self, session_key: str, offset: int = 0) -> Job | None:
        """Get a job from the session's history.

        Args:
            session_key: The session identifier
            offset: 0 = latest, 1 = second latest, etc.
        """
        jobs = self._jobs.get(session_key, [])
        if not jobs:
            return None
        # Jobs are stored oldest first, so latest is at the end
        index = -(offset + 1)
        if abs(index) > len(jobs):
            return None
        return jobs[index]

    async def get_job_history(self, session_key: str) -> list[Job]:
        """Get all jobs for a session (oldest first)."""
        return self._jobs.get(session_key, []).copy()

    async def complete_job(self, job_id: str, final_response: str) -> None:
        """Mark a job as completed."""
        async with self._lock:
            for jobs in self._jobs.values():
                for job in jobs:
                    if job.id == job_id:
                        job.status = "completed"
                        job.final_response = final_response
                        job.completed_at = datetime.now()
                        logger.info(f"Completed job {job_id}")
                        # Persist jobs after completion
                        await self._save()
                        return

    async def fail_job(self, job_id: str, error: str) -> None:
        """Mark a job as failed."""
        async with self._lock:
            for jobs in self._jobs.values():
                for job in jobs:
                    if job.id == job_id:
                        job.status = "error"
                        job.final_response = error
                        job.completed_at = datetime.now()
                        logger.info(f"Failed job {job_id}: {error}")
                        # Persist jobs after failure
                        await self._save()
                        return

    async def abort_job(self, job_id: str) -> bool:
        """Abort a running job."""
        async with self._lock:
            for session_key, jobs in self._jobs.items():
                for job in jobs:
                    if job.id == job_id:
                        if job.status == "running":
                            job.request_abort()
                            logger.info(f"Aborted job {job_id}")
                            # Persist jobs after abort
                            await self._save()
                            return True
                        return False
        return False

    async def set_message_id(self, job_id: str, message_id: str | None) -> None:
        """Set the Telegram message ID for a job."""
        async with self._lock:
            for jobs in self._jobs.values():
                for job in jobs:
                    if job.id == job_id:
                        job.message_id = message_id
                        # Persist jobs after setting message_id
                        await self._save()
                        return

    async def job_add_tool_call(self, job_id: str, name: str, arguments: dict[str, Any], tool_id: str | None = None) -> ToolCallRecord | None:
        """Add a tool call to a job and persist."""
        async with self._lock:
            for jobs in self._jobs.values():
                for job in jobs:
                    if job.id == job_id:
                        record = job.add_tool_call(name, arguments, tool_id)
                        await self._save()
                        return record
            return None

    async def job_update_tool_call(self, job_id: str, tool_id: str, status: ToolCallStatus, result: str = "", error: str = "") -> None:
        """Update a tool call status and persist."""
        async with self._lock:
            for jobs in self._jobs.values():
                for job in jobs:
                    if job.id == job_id:
                        job.update_tool_call(tool_id, status, result, error)
                        await self._save()
                        return


# Global job manager instance
job_manager = JobManager()
