"""High-level programmatic interface to nanobot."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from nanobot.agent.hook import AgentHook, SDKCaptureHook
from nanobot.agent.hooks import create_file_edit_activity_hook
from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import Config
from nanobot.providers.image_generation import image_gen_provider_configs
from nanobot.sdk.clients import MemoryClient, RuntimeClient, SessionClient
from nanobot.sdk.runtime import (
    SDKRuntimeController,
    build_process_direct_kwargs,
    ensure_single_model_selector,
)
from nanobot.sdk.streaming import RunStream, SDKStreamEmitter, SDKStreamingHook
from nanobot.sdk.types import (
    STREAM_EVENT_REASONING_COMPLETED,
    STREAM_EVENT_REASONING_DELTA,
    STREAM_EVENT_RUN_COMPLETED,
    STREAM_EVENT_RUN_FAILED,
    STREAM_EVENT_RUN_STARTED,
    STREAM_EVENT_TEXT_COMPLETED,
    STREAM_EVENT_TEXT_DELTA,
    STREAM_EVENT_TOOL_COMPLETED,
    STREAM_EVENT_TOOL_FAILED,
    STREAM_EVENT_TOOL_STARTED,
    STREAM_EVENT_TYPES,
    RunResult,
    SessionInfo,
    SessionSnapshot,
    StreamEvent,
    StreamEventType,
    result_from_response,
)

__all__ = [
    "Nanobot",
    "RunResult",
    "RunStream",
    "SessionInfo",
    "SessionSnapshot",
    "STREAM_EVENT_REASONING_COMPLETED",
    "STREAM_EVENT_REASONING_DELTA",
    "STREAM_EVENT_RUN_COMPLETED",
    "STREAM_EVENT_RUN_FAILED",
    "STREAM_EVENT_RUN_STARTED",
    "STREAM_EVENT_TEXT_COMPLETED",
    "STREAM_EVENT_TEXT_DELTA",
    "STREAM_EVENT_TOOL_COMPLETED",
    "STREAM_EVENT_TOOL_FAILED",
    "STREAM_EVENT_TOOL_STARTED",
    "STREAM_EVENT_TYPES",
    "StreamEvent",
    "StreamEventType",
]


class Nanobot:
    """Programmatic facade for running the nanobot agent.

    Usage::

        bot = Nanobot.from_config()
        result = await bot.run("Summarize this repo", hooks=[MyHook()])
        print(result.content)
    """

    def __init__(self, loop: AgentLoop, *, config: Config | None = None) -> None:
        self._loop = loop
        self._config = config
        self._runtime_overrides = SDKRuntimeController(loop, config=config)
        self.sessions = SessionClient(loop)
        self.memory = MemoryClient(loop)
        self.runtime = RuntimeClient(loop)

    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
        *,
        workspace: str | Path | None = None,
        model: str | None = None,
        model_preset: str | None = None,
    ) -> Nanobot:
        """Create a Nanobot instance from a config file.

        Args:
            config_path: Path to ``config.json``.  Defaults to
                ``~/.nanobot/config.json``.
            workspace: Override the workspace directory from config.
            model: Override the instance default model.
            model_preset: Override the instance default model preset.
        """
        from nanobot.config.loader import load_config, resolve_config_env_vars

        ensure_single_model_selector(model=model, model_preset=model_preset)
        resolved: Path | None = None
        if config_path is not None:
            resolved = Path(config_path).expanduser().resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Config not found: {resolved}")

        config: Config = resolve_config_env_vars(load_config(resolved))
        if workspace is not None:
            config.agents.defaults.workspace = str(
                Path(workspace).expanduser().resolve()
            )
        if model is not None:
            config.agents.defaults.model_preset = None
            config.agents.defaults.model = model
            config.agents.defaults.provider = "auto"
        elif model_preset is not None:
            config.agents.defaults.model_preset = model_preset

        loop = AgentLoop.from_config(
            config,
            image_generation_provider_configs=image_gen_provider_configs(config),
            hook_factories=[create_file_edit_activity_hook],
        )
        return cls(loop, config=config)

    async def run(
        self,
        message: str,
        *,
        session_key: str = "sdk:default",
        channel: str = "cli",
        chat_id: str = "direct",
        sender_id: str = "user",
        media: list[str] | None = None,
        ephemeral: bool = False,
        hooks: list[AgentHook] | None = None,
        model: str | None = None,
        model_preset: str | None = None,
    ) -> RunResult:
        """Run the agent once and return the result.

        Args:
            message: The user message to process.
            session_key: Session identifier for conversation isolation.
                Different keys get independent history.
            channel: Logical channel label for runtime context.
            chat_id: Logical chat identifier for runtime context.
            sender_id: Logical sender identifier for runtime context.
            media: Optional local media paths attached to the message.
            ephemeral: If true, do not persist the turn or compact session history.
            hooks: Optional lifecycle hooks for this run.
            model: Override the model for this run only.
            model_preset: Override the model preset for this run only.
        """
        capture = SDKCaptureHook()
        per_run_hooks = [capture, *(hooks or [])]
        async with self._runtime_overrides.override(model=model, model_preset=model_preset):
            kwargs = build_process_direct_kwargs(
                session_key=session_key,
                channel=channel,
                chat_id=chat_id,
                sender_id=sender_id,
                media=media,
                ephemeral=ephemeral,
            )
            response = await self._loop.process_direct(
                message,
                **kwargs,
                hooks=per_run_hooks,
            )

        return result_from_response(response, capture)

    async def run_streamed(
        self,
        message: str,
        *,
        session_key: str = "sdk:default",
        channel: str = "cli",
        chat_id: str = "direct",
        sender_id: str = "user",
        media: list[str] | None = None,
        ephemeral: bool = False,
        hooks: list[AgentHook] | None = None,
        model: str | None = None,
        model_preset: str | None = None,
    ) -> RunStream:
        """Start a streamed run and return a handle for events and final result."""
        ensure_single_model_selector(model=model, model_preset=model_preset)
        queue: asyncio.Queue[StreamEvent | object] = asyncio.Queue(maxsize=256)
        emitter = SDKStreamEmitter(queue)
        stream_hook = SDKStreamingHook(emitter)
        capture = SDKCaptureHook()
        per_run_hooks = [capture, stream_hook, *(hooks or [])]

        async def _on_stream(delta: str) -> None:
            await emitter.text_delta(delta)

        async def _on_stream_end(*_args: Any, resuming: bool = False, **_kwargs: Any) -> None:
            await emitter.text_completed(resuming=resuming)

        async def _run() -> RunResult:
            async with self._runtime_overrides.override(model=model, model_preset=model_preset):
                kwargs = build_process_direct_kwargs(
                    session_key=session_key,
                    channel=channel,
                    chat_id=chat_id,
                    sender_id=sender_id,
                    media=media,
                    ephemeral=ephemeral,
                    on_stream=_on_stream,
                    on_stream_end=_on_stream_end,
                )
                await emitter.emit(StreamEvent(
                    type=STREAM_EVENT_RUN_STARTED,
                    metadata={
                        "session_key": session_key,
                        "channel": channel,
                        "chat_id": chat_id,
                        "sender_id": sender_id,
                        "model": self._loop.model,
                        "model_preset": (
                            model_preset if model_preset is not None else self._loop.model_preset
                        ),
                    },
                ))
                try:
                    response = await self._loop.process_direct(
                        message,
                        **kwargs,
                        hooks=per_run_hooks,
                    )
                    await emitter.text_completed(resuming=False, force=False)
                    result = result_from_response(response, capture)
                    await emitter.emit(StreamEvent(
                        type=STREAM_EVENT_RUN_COMPLETED,
                        content=result.content,
                        result=result,
                        usage=dict(result.usage),
                        metadata=dict(result.metadata),
                    ))
                    return result
                except Exception as exc:
                    await emitter.emit(StreamEvent(
                        type=STREAM_EVENT_RUN_FAILED,
                        error=str(exc),
                        metadata={"exception_type": type(exc).__name__},
                    ))
                    raise
                finally:
                    emitter.close()

        task = asyncio.create_task(_run())
        return RunStream(task, queue)

    async def stream(
        self,
        message: str,
        *,
        session_key: str = "sdk:default",
        channel: str = "cli",
        chat_id: str = "direct",
        sender_id: str = "user",
        media: list[str] | None = None,
        ephemeral: bool = False,
        hooks: list[AgentHook] | None = None,
        model: str | None = None,
        model_preset: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream events for one agent turn."""
        run = await self.run_streamed(
            message,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            sender_id=sender_id,
            media=media,
            ephemeral=ephemeral,
            hooks=hooks,
            model=model,
            model_preset=model_preset,
        )
        try:
            async for event in run.stream_events():
                yield event
            await run.wait()
        finally:
            if not run.done:
                await run.aclose()

    async def aclose(self) -> None:
        """Release resources held by this instance (MCP connections, etc.)."""
        await self._loop.close_mcp()

    async def __aenter__(self) -> Nanobot:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
