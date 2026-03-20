"""Shared test helpers for the nanobot test suite.

This module provides reusable test utilities that are imported directly by
test files.  Unlike conftest.py fixtures, these are plain Python classes and
functions that tests import explicitly.
"""

from __future__ import annotations

from typing import Any

from nanobot.providers.base import LLMProvider, LLMResponse


class ScriptedProvider(LLMProvider):
    """LLM provider that returns pre-configured responses in order.

    Each call to ``chat()`` pops the next response off the queue.  When the
    queue is exhausted a fallback ``"(no more scripted responses)"`` is
    returned.

    ``call_log`` records the full set of call parameters for every invocation
    so tests can assert on message counts, tool presence, model selection,
    metadata, and the full message list.
    """

    def __init__(self, responses: list[LLMResponse], *, model_name: str = "test-model") -> None:
        super().__init__()
        self._responses = list(responses)
        self._index = 0
        self._model_name = model_name
        self.call_log: list[dict[str, Any]] = []

    def get_default_model(self) -> str:
        return self._model_name

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.call_log.append(
            {
                # Counts / flags — used by test_agent_loop and test_no_answer_recovery
                "messages_count": len(messages),
                "has_tools": tools is not None,
                "tool_names": [t["function"]["name"] for t in (tools or [])],
                # Full payload — used by golden and workflow tests
                "messages": [dict(m) for m in messages],
                "tools": tools,
                # Scalar fields — used by coordinator and observability tests
                "model": model,
                "temperature": temperature,
                "metadata": metadata,
                # Convenience excerpt — used by test_multiagent_planning
                "last_user_msg": next(
                    (m.get("content", "")[:120] for m in reversed(messages) if m["role"] == "user"),
                    "",
                ),
            }
        )
        if self._index >= len(self._responses):
            return LLMResponse(content="(no more scripted responses)")
        resp = self._responses[self._index]
        self._index += 1
        return resp
