"""Tests for HeartbeatService._is_deliverable and _tick suppression."""

import pytest

from nanobot.heartbeat.service import HeartbeatService
from nanobot.providers.base import LLMResponse, ToolCallRequest

# ---------------------------------------------------------------------------
# _is_deliverable unit tests
# ---------------------------------------------------------------------------


class TestIsDeliverable:
    """Verify the pre-evaluator deliverability filter."""

    def test_normal_report_is_deliverable(self):
        assert HeartbeatService._is_deliverable(
            "2 new emails — invoice from Zain, meeting rescheduled to 3pm."
        )

    def test_short_dismissal_is_deliverable(self):
        assert HeartbeatService._is_deliverable("All clear.")

    def test_finalization_fallback_blocked(self):
        assert not HeartbeatService._is_deliverable(
            "I completed the tool steps but couldn't produce a final answer. "
            "Please try again or narrow the task."
        )

    def test_leaked_heartbeat_md_reference_blocked(self):
        assert not HeartbeatService._is_deliverable(
            "Yes — HEARTBEAT.md has active tasks listed. They are: "
            "Check Gmail for important messages, Check Calendar."
        )

    def test_leaked_awareness_md_reference_blocked(self):
        assert not HeartbeatService._is_deliverable(
            "I reviewed AWARENESS.md and found no new signals."
        )

    def test_leaked_judgment_call_blocked(self):
        assert not HeartbeatService._is_deliverable(
            "Best judgment call: stay quiet."
        )

    def test_leaked_decision_logic_blocked(self):
        assert not HeartbeatService._is_deliverable(
            "Strict HEARTBEAT interpretation. Decision logic says SHORT UPDATE."
        )

    def test_leaked_valid_options_blocked(self):
        assert not HeartbeatService._is_deliverable(
            "The valid options are FULL REPORT, SHORT UPDATE, or SILENT."
        )

    def test_leaked_my_instructions_blocked(self):
        assert not HeartbeatService._is_deliverable(
            "My instructions say to check Gmail and Calendar."
        )

    def test_leaked_supposed_to_blocked(self):
        assert not HeartbeatService._is_deliverable(
            "I am supposed to scan for urgent emails."
        )

    def test_case_insensitive(self):
        assert not HeartbeatService._is_deliverable(
            "HEARTBEAT.MD has tasks listed."
        )

    def test_empty_string_is_deliverable(self):
        """Empty string won't reach _is_deliverable in practice (caught earlier),
        but should not crash."""
        assert HeartbeatService._is_deliverable("")


# ---------------------------------------------------------------------------
# _tick integration: non-deliverable responses never reach evaluator/notify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_suppresses_finalization_fallback(tmp_path, monkeypatch) -> None:
    """Finalization fallback should be caught before the evaluator runs."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] check inbox", encoding="utf-8")

    from nanobot.providers.base import LLMProvider

    class StubProvider(LLMProvider):
        async def chat(self, **kwargs) -> LLMResponse:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="hb_1", name="heartbeat",
                        arguments={"action": "run", "tasks": "check inbox"},
                    )
                ],
            )

        def get_default_model(self) -> str:
            return "test-model"

    notified: list[str] = []
    evaluator_called = False

    async def _on_execute(tasks: str) -> str:
        return (
            "I completed the tool steps but couldn't produce a final answer. "
            "Please try again or narrow the task."
        )

    async def _on_notify(response: str) -> None:
        notified.append(response)

    async def _eval_always_notify(*a, **kw):
        nonlocal evaluator_called
        evaluator_called = True
        return True

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _eval_always_notify)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=StubProvider(),
        model="test-model",
        on_execute=_on_execute,
        on_notify=_on_notify,
    )

    await service._tick()

    assert notified == [], "Finalization fallback should not reach the user"
    assert not evaluator_called, "Evaluator should not be called for non-deliverable responses"


@pytest.mark.asyncio
async def test_tick_suppresses_leaked_reasoning(tmp_path, monkeypatch) -> None:
    """Leaked internal reasoning should be caught before the evaluator runs."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] check status", encoding="utf-8")

    from nanobot.providers.base import LLMProvider

    class StubProvider(LLMProvider):
        async def chat(self, **kwargs) -> LLMResponse:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="hb_1", name="heartbeat",
                        arguments={"action": "run", "tasks": "check status"},
                    )
                ],
            )

        def get_default_model(self) -> str:
            return "test-model"

    notified: list[str] = []

    async def _on_execute(tasks: str) -> str:
        return "HEARTBEAT.md has active tasks listed. They are: Check Gmail."

    async def _on_notify(response: str) -> None:
        notified.append(response)

    async def _eval_always_notify(*a, **kw):
        return True

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _eval_always_notify)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=StubProvider(),
        model="test-model",
        on_execute=_on_execute,
        on_notify=_on_notify,
    )

    await service._tick()

    assert notified == [], "Leaked reasoning should not reach the user"


@pytest.mark.asyncio
async def test_tick_delivers_normal_report(tmp_path, monkeypatch) -> None:
    """Normal reports should pass through deliverability and evaluator."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] check inbox", encoding="utf-8")

    from nanobot.providers.base import LLMProvider

    class StubProvider(LLMProvider):
        async def chat(self, **kwargs) -> LLMResponse:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="hb_1", name="heartbeat",
                        arguments={"action": "run", "tasks": "check inbox"},
                    )
                ],
            )

        def get_default_model(self) -> str:
            return "test-model"

    notified: list[str] = []

    async def _on_execute(tasks: str) -> str:
        return "3 new emails — client proposal from Zain, invoice, meeting reminder."

    async def _on_notify(response: str) -> None:
        notified.append(response)

    async def _eval_always_notify(*a, **kw):
        return True

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _eval_always_notify)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=StubProvider(),
        model="test-model",
        on_execute=_on_execute,
        on_notify=_on_notify,
    )

    await service._tick()

    assert notified == ["3 new emails — client proposal from Zain, invoice, meeting reminder."]
