"""Scripted test harness helpers for agent runner tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest


def tool_call(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    id: str | None = None,
) -> ToolCallRequest:
    """Build a stable tool call for scripted runner tests."""
    return ToolCallRequest(
        id=id or f"{name}_call",
        name=name,
        arguments=arguments or {},
    )


@dataclass(slots=True)
class ProviderRequest:
    """A provider request captured by ``ScriptedProvider``."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    kwargs: dict[str, Any]


@dataclass(slots=True)
class ToolExecution:
    """A tool invocation captured by ``ScriptedTools``."""

    name: str
    arguments: dict[str, Any]


class ScriptedTools:
    """Minimal tool registry double for scripted runner tests."""

    def __init__(
        self,
        results: Iterable[Any],
        *,
        definitions: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        self._results = deque(results)
        self._definitions = list(definitions or [])
        self.calls: list[ToolExecution] = []

    def get_definitions(self) -> list[dict[str, Any]]:
        return deepcopy(self._definitions)

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append(ToolExecution(name=name, arguments=deepcopy(arguments)))
        if not self._results:
            raise AssertionError(f"ScriptedTools received unexpected call to {name}")
        result = self._results.popleft()
        if isinstance(result, BaseException):
            raise result
        return result


class ScriptedProvider:
    """Minimal provider double that returns pre-planned LLM responses.

    The harness records every request so tests can assert the exact transcript
    the runner sends back to the model after tool calls, injections, and
    context governance.
    """

    supports_progress_deltas = False

    def __init__(
        self,
        responses: Iterable[LLMResponse],
        *,
        default_model: str = "test-model",
        stream_chunks: Sequence[Sequence[str] | None] | None = None,
    ) -> None:
        self._responses = deque(responses)
        self._stream_chunks = deque(stream_chunks or [])
        self._default_model = default_model
        self.generation = GenerationSettings()
        self.requests: list[ProviderRequest] = []

    def get_default_model(self) -> str:
        return self._default_model

    def estimate_prompt_tokens(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> tuple[int, str]:
        return (0, "scripted")

    async def chat_with_retry(self, **kwargs: Any) -> LLMResponse:
        self._record(kwargs)
        return self._next_response()

    async def chat_stream_with_retry(
        self,
        *,
        on_content_delta=None,
        on_thinking_delta=None,
        **kwargs: Any,
    ) -> LLMResponse:
        self._record(kwargs)
        response = self._next_response()
        if response.reasoning_content and on_thinking_delta is not None:
            await on_thinking_delta(response.reasoning_content)
        if on_content_delta is not None:
            chunks = self._stream_chunks.popleft() if self._stream_chunks else None
            for chunk in chunks if chunks is not None else [response.content or ""]:
                await on_content_delta(chunk)
        return response

    def _record(self, kwargs: dict[str, Any]) -> None:
        self.requests.append(
            ProviderRequest(
                messages=deepcopy(kwargs.get("messages", [])),
                tools=deepcopy(kwargs.get("tools")),
                kwargs={k: v for k, v in kwargs.items() if k not in {"messages", "tools"}},
            ),
        )

    def _next_response(self) -> LLMResponse:
        if not self._responses:
            raise AssertionError("ScriptedProvider received more requests than responses")
        return self._responses.popleft()


def assert_tool_results_are_paired(messages: Sequence[dict[str, Any]]) -> None:
    """Assert every tool result references a prior assistant tool call."""
    declared: set[str] = set()
    orphans: list[str] = []
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict):
                    call_id = call.get("id")
                    if isinstance(call_id, str):
                        declared.add(call_id)
        if message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if isinstance(call_id, str) and call_id not in declared:
                orphans.append(call_id)
    assert orphans == [], f"orphan tool_call_ids: {orphans}"
