"""Evaluation runner that executes scenarios against a lightweight agent loop."""

from __future__ import annotations

import time
from typing import Any

from nanobot.eval.scenario import EvalMetrics, EvalResult, Scenario
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.utils.helpers import build_assistant_message


class ScriptedProvider(LLMProvider):
    """Provider that returns pre-scripted responses for deterministic evaluation."""

    def __init__(self, responses: list[LLMResponse | Exception]):
        super().__init__()
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        if self._responses:
            resp = self._responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp
        return LLMResponse(content="[no more scripted responses]", tool_calls=[])

    def get_default_model(self) -> str:
        return "eval-scripted"


class EvalRunner:
    """Runs a Scenario through a minimal agent loop and returns metrics.

    This is intentionally lightweight — it mimics the core iteration logic
    from ``AgentLoop._run_agent_loop`` without requiring a MessageBus,
    SessionManager, or real tool implementations.  Tool calls are resolved
    via the scenario's ``tool_results`` mapping (tool-name → static result).
    """

    async def run(self, scenario: Scenario) -> EvalResult:
        """Execute *scenario* and evaluate all criteria."""
        provider = ScriptedProvider(list(scenario.scripted_responses))
        metrics = EvalMetrics()
        start = time.monotonic()

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
        ]
        for user_msg in scenario.user_messages:
            messages.append({"role": "user", "content": user_msg})

        final_output: str | None = None
        iteration = 0

        try:
            while iteration < scenario.max_iterations:
                iteration += 1

                response = await provider.chat_with_retry(
                    messages=messages,
                    tools=[],  # definitions unused by ScriptedProvider
                    model="eval-scripted",
                )

                # Accumulate token usage reported by the response
                metrics.total_tokens += sum(response.usage.values())

                if response.has_tool_calls:
                    tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
                    messages.append(
                        build_assistant_message(
                            response.content or "",
                            tool_calls=tool_call_dicts,
                        )
                    )

                    for tc in response.tool_calls:
                        metrics.tools_called.append(tc.name)
                        result = scenario.tool_results.get(tc.name, f"Mock result for {tc.name}")
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "name": tc.name,
                                "content": result,
                            }
                        )
                else:
                    final_output = response.content
                    break

        except Exception as e:
            metrics.errors.append(f"{type(e).__name__}: {e}")

        metrics.total_iterations = iteration
        elapsed = time.monotonic() - start
        metrics.duration_ms = int(elapsed * 1000)

        result = EvalResult(
            scenario_name=scenario.name,
            final_output=final_output,
            metrics=metrics,
        )

        # Evaluate criteria
        for criterion in scenario.criteria:
            result.criteria_results.append(criterion.evaluate(result))

        return result

    async def run_multiple(self, scenarios: list[Scenario]) -> list[EvalResult]:
        """Run several scenarios and return all results."""
        return [await self.run(s) for s in scenarios]
