"""Subagent manager for background task execution (ADK-based)."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from loguru import logger

from scorpion.adk.tools import SUBAGENT_TOOLS, set_runtime_refs
from scorpion.bus.events import InboundMessage
from scorpion.bus.queue import MessageBus
from scorpion.config.schema import FLASH_MODEL
from scorpion.providers.base import LLMProvider


class SubagentManager:
    """Manages background subagent execution using ADK."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from scorpion.config.schema import ExecToolConfig

        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or FLASH_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}
        self._session_service = InMemorySessionService()

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id}

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)

        logger.info(
            "[Subagent {}] Spawned — label={!r} session={}",
            task_id, display_label, session_key or "none",
        )
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """Execute the subagent task using ADK and announce the result."""
        logger.info(
            "[Subagent {}] Starting — label={!r} origin={}:{} task={!r}",
            task_id, label, origin["channel"], origin["chat_id"], task[:100],
        )

        try:
            instruction = self._build_subagent_prompt()

            agent = LlmAgent(
                name=f"subagent_{task_id}",
                model=self.model,
                instruction=instruction,
                tools=list(SUBAGENT_TOOLS),
                generate_content_config=types.GenerateContentConfig(
                    temperature=self.temperature,
                    max_output_tokens=self.max_tokens,
                ),
            )
            logger.debug("[Subagent {}] ADK agent created with {} tools", task_id, len(SUBAGENT_TOOLS))

            runner = Runner(
                app_name="scorpion_subagent",
                agent=agent,
                session_service=self._session_service,
            )

            # Ensure subagent tools can reach the message bus for send_message
            set_runtime_refs(bus_publish=self.bus.publish_outbound)

            # Build state for subagent tools
            allowed_dir = str(self.workspace) if self.restrict_to_workspace else ""
            state = {
                "app:workspace": str(self.workspace),
                "app:brave_api_key": self.brave_api_key or "",
                "app:exec_timeout": str(self.exec_config.timeout),
                "app:exec_deny": json.dumps(self.exec_config.deny_patterns) if self.exec_config.deny_patterns else "",
                "app:exec_allow": json.dumps(self.exec_config.allow_patterns) if self.exec_config.allow_patterns else "",
                "app:exec_restrict": "true" if self.restrict_to_workspace else "",
                "app:exec_path": self.exec_config.path_append or "",
                "app:allowed_dir": allowed_dir,
                "app:max_iterations": "15",
                # Flag so tools (e.g. generate_video) know they're inside a
                # subagent and should do blocking work instead of re-spawning.
                "app:is_subagent": "true",
                # Pass origin channel so subagent tools (send_message) know where to deliver
                "temp:channel": origin["channel"],
                "temp:chat_id": origin["chat_id"],
            }

            session = await self._session_service.create_session(
                app_name="scorpion_subagent",
                user_id=f"subagent:{task_id}",
                state=state,
            )
            logger.debug("[Subagent {}] ADK session created, running task...", task_id)

            user_content = types.Content(
                role="user",
                parts=[types.Part(text=task)],
            )

            final_result = None
            event_count = 0
            async for event in runner.run_async(
                user_id=session.user_id,
                session_id=session.id,
                new_message=user_content,
            ):
                event_count += 1
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            final_result = part.text
                            logger.debug(
                                "[Subagent {}] Event #{} text: {!r}",
                                task_id, event_count, part.text[:120],
                            )

                if event.error_message:
                    logger.error("[Subagent {}] ADK error: {}", task_id, event.error_message)
                    final_result = final_result or f"Error: {event.error_message}"

            if final_result is None:
                final_result = "Task completed but no final response was generated."

            logger.info(
                "[Subagent {}] Completed successfully after {} events",
                task_id, event_count,
            )
            await self._announce_result(task_id, label, task, final_result, origin, "ok")

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("[Subagent {}] Failed with exception: {}", task_id, e, exc_info=True)
            await self._announce_result(task_id, label, task, error_msg, origin, "error")

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""

        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.info(
            "[Subagent {}] Announced {} result to {}:{}",
            task_id, status_text,
            origin["channel"], origin["chat_id"],
        )

    def _build_subagent_prompt(self) -> str:
        """Build a focused system prompt for the subagent."""
        from scorpion.agent.context import ContextBuilder
        from scorpion.agent.skills import SkillsLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        parts = [
            f"""# Subagent

{time_ctx}

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task. Your final response will be reported back to the main agent.

## Workspace
{self.workspace}

## Media Generation
You can generate videos using the generate_video tool (Google Veo 3.1, takes 1-5 minutes).
After generating media, use send_message with media=[file_path] to deliver it directly to the user.
Always include a brief description of what was generated in the message content."""
        ]

        skills_summary = SkillsLoader(self.workspace).build_skills_summary()
        if skills_summary:
            parts.append(
                f"## Skills\n\nRead SKILL.md with read_file to use a skill.\n\n{skills_summary}"
            )

        return "\n\n".join(parts)

    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [
            self._running_tasks[tid]
            for tid in self._session_tasks.get(session_key, [])
            if tid in self._running_tasks and not self._running_tasks[tid].done()
        ]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)
