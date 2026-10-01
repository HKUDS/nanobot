"""Public structured decision client and request validation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, cast

import httpx

from .errors import DecisionClientClosedError, DecisionProtocolError
from .models import (
    ChoiceQuestion,
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
    NoulQuestion,
    ScoreQuestion,
    StructuredInput,
    validate_structured_input,
)
from .providers import DecisionProviderSettings, resolve_provider_settings_from_config
from .transports import SystemOneTransport

if TYPE_CHECKING:
    from nanobot.config.schema import Config


class StructuredDecisionClient:
    """Evaluate typed questions through a registered decision provider.

    The caller owns the client's lifetime and must close it with `aclose()` or
    `async with`. Passing `transport=` transfers ownership of that transport to the
    client: do not close it separately or share it with another client.
    """

    def __init__(
        self,
        *,
        model: str,
        provider_settings: DecisionProviderSettings,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        model_value: Any = model
        if not isinstance(model_value, str) or not model_value.strip():
            raise DecisionProtocolError("Model cannot be empty")
        model = model_value
        timeout_value: Any = timeout
        if (
            isinstance(timeout_value, bool)
            or not isinstance(timeout_value, (int, float))
            or not math.isfinite(timeout_value)
            or timeout_value <= 0
            or timeout_value > 120
        ):
            raise ValueError("Decision timeout must be within (0, 120]")

        self.model = model
        self.provider = provider_settings.name
        self.protocol = provider_settings.protocol
        self._wire_transport = SystemOneTransport(
            provider_settings=provider_settings,
            timeout=float(timeout),
            transport=transport,
        )

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> Self:
        """Build a client from decision settings and the explicitly selected provider.

        An injected `transport` becomes owned by the returned client and is closed by it.
        """
        decision_config = config.structured_decision
        provider_settings = resolve_provider_settings_from_config(
            config,
            provider=decision_config.provider,
            protocol=decision_config.protocol,
        )
        return cls(
            model=decision_config.model,
            provider_settings=provider_settings,
            timeout=decision_config.timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        """Close HTTP resources; safe to call repeatedly.

        Waits for in-flight evaluations to finish. Evaluations started after closing
        begins raise `DecisionClientClosedError`, and a closed client stays closed.
        """
        await self._wire_transport.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def evaluate(
        self,
        *,
        state: StructuredInput,
        questions: Mapping[str, DecisionQuestion],
    ) -> DecisionResult:
        """Send one state and its typed questions to the selected decision endpoint."""
        # Reject evaluations once aclose() has started, so a closing client cannot be reused.
        if self._wire_transport.closed:
            raise DecisionClientClosedError("Decision client is closed")
        request = self._build_request(state=state, questions=questions)
        return await self._wire_transport.evaluate(request)

    def _build_request(
        self,
        *,
        state: StructuredInput,
        questions: Mapping[str, DecisionQuestion],
    ) -> DecisionRequest:
        validate_structured_input(state, "State")
        questions_value: Any = questions
        if not isinstance(questions_value, Mapping):
            raise DecisionProtocolError("Questions must be a mapping")

        validated_questions: dict[str, DecisionQuestion] = {}
        question_entries = cast(Mapping[object, object], questions_value)
        for question_id_value, question_value in question_entries.items():
            if not isinstance(question_id_value, str) or not question_id_value.strip():
                raise DecisionProtocolError("Question ID cannot be empty")
            if not isinstance(question_value, (NoulQuestion, ChoiceQuestion, ScoreQuestion)):
                raise DecisionProtocolError(
                    f"Question {question_id_value!r} has an invalid shape"
                )
            question_id = question_id_value
            question = question_value
            question.validate()
            validated_questions[question_id] = question

        return DecisionRequest(
            model=self.model,
            state=state,
            questions=validated_questions,
        )
