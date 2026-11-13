from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCallContext,
    ProviderConversationState,
)
from nanobot.providers.conversation_state import ProviderConversationStateController
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.images import image_input_ids, image_inputs_available, state_image_input_ids

_IMAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64,c3ludGhldGlj"}}
_NATIVE_IMAGE = {"type": "input_image", "image_url": _IMAGE["image_url"]["url"]}


class ReplayProvider(LLMProvider):
    def __init__(self, name: str, response: LLMResponse) -> None:
        super().__init__(provider_name=name)
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def get_default_model(self) -> str:
        return self.provider_name

    def can_resume_conversation_state(self, state: ProviderConversationState, model: str | None = None) -> bool:
        return state.provider == self.provider_name and state.model == (model or self.get_default_model())

    async def chat(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        return self.response

    async def chat_with_context(self, *, provider_context: ProviderCallContext, **kwargs: Any) -> LLMResponse:
        return await self.chat(provider_context=provider_context, **kwargs)

    async def aclose(self) -> None:
        self.closed = True


def _state() -> ProviderConversationState:
    return ProviderConversationState(
        kind="openai_responses", provider="primary", model="primary", version=1,
        payload={"items": [{"role": "user", "content": [_NATIVE_IMAGE]}]},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_fallback_requires_complete_portable_image_input(complete: bool) -> None:
    primary = ReplayProvider("primary", LLMResponse("upstream unavailable", finish_reason="error", error_status_code=503))
    candidate = ReplayProvider("alternate", LLMResponse("saw the image"))
    provider = FallbackProvider(
        primary, [ModelPresetConfig(model="alternate", provider="custom")],
        provider_factory=lambda _: candidate,
    )
    messages = [{"role": "user", "content": [_IMAGE] if complete else "[image: screenshot.png]"}]
    before = deepcopy(messages)
    state = _state()
    response = await provider.chat_with_context(
        messages=messages, model="primary", provider_context=ProviderCallContext(conversation_state=state),
    )
    assert messages == before
    assert candidate.closed
    if complete:
        assert response.content == "saw the image"
        assert candidate.calls[0]["messages"] == messages
        assert candidate.calls[0]["provider_context"].conversation_state is None
    else:
        assert response.finish_reason == "error"
        assert response.content == "upstream unavailable"
        assert candidate.calls == []
        assert state_image_input_ids(state)


@pytest.mark.parametrize("native,error_kind", [(False, "unknown"), (True, "unknown"), (True, "input_unavailable")])
def test_nontransient_failure_retains_image_identity_not_invalid_native_state(native: bool, error_kind: str) -> None:
    provider = ReplayProvider("primary", LLMResponse("unused"))
    messages = [{"role": "user", "content": [_IMAGE] if not native else "[image: screenshot.png]"}]
    controller = ProviderConversationStateController(
        provider=provider, model="primary", messages=messages, state=_state() if native else None,
    )
    controller.prepare_request(messages, context_window_tokens=None)
    controller.observe_response(LLMResponse(
        "bad request", finish_reason="error", error_kind=error_kind,
        error_status_code=None if error_kind == "input_unavailable" else 400,
    ), messages)
    assert controller.finish(messages) is None
    assert controller.failed_image_inputs == image_input_ids([_IMAGE])
    assert not image_inputs_available(controller.failed_image_inputs, [{"role": "user", "content": "[image: screenshot.png]"}])


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("source", ["public", "native", "missing", "wrong-model"])
async def test_recovery_preflight_requires_actual_images(stream: bool, source: str) -> None:
    provider = ReplayProvider("primary", LLMResponse("image accepted"))
    state = _state() if source in {"native", "wrong-model"} else None
    messages = [{"role": "user", "content": [_IMAGE] if source == "public" else "[image: screenshot.png]"}]
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry
    response = await call(
        messages=messages, model="different" if source == "wrong-model" else "primary",
        provider_context=ProviderCallContext(conversation_state=state, required_image_inputs=image_input_ids([_IMAGE])),
    )
    if source in {"missing", "wrong-model"}:
        assert response.finish_reason == "error"
        assert response.error_kind == "input_unavailable"
        assert "Send the images again" in (response.content or "")
        assert provider.calls == []
    else:
        assert response.content == "image accepted"
        assert len(provider.calls) == 1


def test_image_replay_keeps_multiplicity_and_does_not_read_paths() -> None:
    required = image_input_ids([_IMAGE, _IMAGE])
    assert not image_inputs_available(required, [{"role": "user", "content": [_IMAGE]}])
    assert image_inputs_available(required, [{"role": "user", "content": [_IMAGE, _IMAGE]}])
    assert image_input_ids({"role": "user", "content": "[image: screenshot.png]", "media": ["screenshot.png"]}) == ()


@pytest.mark.asyncio
async def test_accepted_compaction_retires_prior_image_requirements() -> None:
    provider = ReplayProvider("primary", LLMResponse("unused"))
    messages = [{"role": "user", "content": "Summarize the prior image"}]
    controller = ProviderConversationStateController(
        provider=provider, model="primary", messages=messages, state=_state(),
        required_image_inputs=image_input_ids([_IMAGE]),
    )
    context = controller.prepare_request(messages, context_window_tokens=None)
    assert context is not None and context.on_native_compaction is not None
    compacted = ProviderConversationState(
        kind="openai_responses", provider="primary", model="primary", version=1,
        payload={"items": [{"type": "compaction", "encrypted_content": "synthetic-summary"}]},
    )
    await context.on_native_compaction(compacted)
    controller.observe_response(LLMResponse("bad request", finish_reason="error", error_status_code=400), messages)
    assert controller.finish(messages) is None
    assert controller.failed_image_inputs == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("pre_request_compaction", [False, True])
async def test_resumed_runner_continues_after_compaction_and_completed_tool(pre_request_compaction: bool) -> None:
    from unittest.mock import AsyncMock

    from nanobot.agent.runner import AgentRunner, AgentRunSpec
    from nanobot.agent.tools.base import Tool
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.providers.base import GenerationSettings, ToolCallRequest
    from nanobot.utils.llm_runtime import LLMRuntime

    class CompletedTool(Tool):
        name = "completed"
        description = "Return synthetic evidence"
        parameters = {"type": "object", "properties": {}}
        executions = 0

        async def execute(self, **kwargs: Any) -> str:
            self.executions += 1
            return "synthetic tool result"

    compacted = ProviderConversationState(
        kind="openai_responses", provider="primary", model="primary", version=1,
        payload={"items": [{"type": "compaction", "encrypted_content": "synthetic-summary"}]},
    )

    class CompactingProvider(ReplayProvider):
        async def chat_stream_with_context(self, *, provider_context: ProviderCallContext, **kwargs: Any) -> LLMResponse:
            self.calls.append({**kwargs, "provider_context": provider_context})
            if len(self.calls) == 1:
                assert provider_context.required_image_inputs
                if pre_request_compaction:
                    assert provider_context.on_native_compaction is not None
                    await provider_context.on_native_compaction(compacted)
                return LLMResponse(
                    content=None, finish_reason="tool_calls", provider_state=compacted,
                    provider_compaction_applied=True, provider_compaction_state=compacted,
                    provider_compaction_scope="prior_context" if pre_request_compaction else "current_request",
                    tool_calls=[ToolCallRequest("completed-once", "completed", {})],
                )
            assert provider_context.required_image_inputs == ()
            return LLMResponse("Completed after compaction.", provider_state=compacted)

    provider = CompactingProvider("primary", LLMResponse("unused"))
    tool = CompletedTool()
    tools = ToolRegistry()
    tools.register(tool)
    result = await AgentRunner().run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "Continue from the saved image"}],
        tools=tools,
        runtime=LLMRuntime(provider=provider, model="primary", generation=GenerationSettings(), context_window_tokens=200_000),
        max_iterations=3, max_tool_result_chars=16_000,
        provider_state=_state(), required_image_inputs=image_input_ids([_IMAGE]),
        consolidate_history=AsyncMock(return_value=None),
    ))
    assert result.stop_reason == "completed"
    assert result.final_content == "Completed after compaction."
    assert len(provider.calls) == 2
    assert tool.executions == 1
    assert any(message.get("tool_call_id") == "completed-once" for message in provider.calls[1]["messages"])
    assert result.required_image_inputs == ()
