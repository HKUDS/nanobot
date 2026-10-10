"""Public structured decision client and request validation."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, cast

import httpx
from loguru import logger

from .errors import (
    DecisionClientClosedError,
    DecisionHttpError,
    DecisionProtocolError,
    DecisionTimeoutError,
    DecisionTransportError,
    MissingCredentialsError,
)
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
    from nanobot.llm_usage.models import LLMCallRecord

LLMCallObserver = Callable[["LLMCallRecord"], None]


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
        self._llm_call_observer: LLMCallObserver | None = None
        self._wire_transport = SystemOneTransport(
            provider_settings=provider_settings,
            timeout=float(timeout),
            transport=transport,
        )

    def set_llm_call_observer(self, observer: LLMCallObserver | None) -> None:
        """Attach a fail-open observer for each attempted decision call."""
        self._llm_call_observer = observer

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
        observer = self._llm_call_observer
        if observer is None:
            return await self._wire_transport.evaluate(request)

        started_at_ms = time.time_ns() // 1_000_000
        started_at_ns = time.monotonic_ns()
        try:
            result = await self._wire_transport.evaluate(request)
        except asyncio.CancelledError as exc:
            self._record_llm_call(
                observer,
                started_at_ms=started_at_ms,
                started_at_ns=started_at_ns,
                error=exc,
            )
            raise
        except (DecisionClientClosedError, MissingCredentialsError):
            raise
        except Exception as exc:
            self._record_llm_call(
                observer,
                started_at_ms=started_at_ms,
                started_at_ns=started_at_ns,
                error=exc,
            )
            raise
        self._record_llm_call(
            observer,
            started_at_ms=started_at_ms,
            started_at_ns=started_at_ns,
            result=result,
        )
        return result

    def _record_llm_call(
        self,
        observer: LLMCallObserver,
        *,
        started_at_ms: int,
        started_at_ns: int,
        result: DecisionResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        try:
            from nanobot.llm_usage.context import current_llm_usage_source
            from nanobot.llm_usage.models import LLMCallRecord
            from nanobot.providers.base import LLMUsage

            usage = None
            model = self.model
            error_status_code = None
            error_kind = None
            if result is not None:
                model = result.model
                decision_usage = result.usage
                if decision_usage is not None:
                    input_tokens = decision_usage.input_tokens
                    output_tokens = decision_usage.output_tokens
                    if (
                        isinstance(input_tokens, int)
                        and not isinstance(input_tokens, bool)
                        and input_tokens >= 0
                        and isinstance(output_tokens, int)
                        and not isinstance(output_tokens, bool)
                        and output_tokens >= 0
                    ):
                        usage = LLMUsage.reported(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        )
                finish_reason = "stop"
            elif isinstance(error, asyncio.CancelledError):
                finish_reason = "cancelled"
                error_kind = "cancelled"
            else:
                finish_reason = "error"
                error_kind = "other"
                if isinstance(error, DecisionHttpError):
                    error_status_code = error.status_code
                    error_kind = "http"
                elif isinstance(error, DecisionTimeoutError):
                    error_kind = "timeout"
                elif isinstance(error, DecisionTransportError):
                    error_kind = "connection"
                elif isinstance(error, DecisionProtocolError):
                    error_kind = "server_error"

            observer(LLMCallRecord(
                started_at_ms=started_at_ms,
                duration_ms=max(0, (time.monotonic_ns() - started_at_ns) // 1_000_000),
                provider=self.provider,
                model=model,
                source=current_llm_usage_source(),
                stream=False,
                finish_reason=finish_reason,
                usage=usage,
                error_status_code=error_status_code,
                error_kind=error_kind,
            ))
        except Exception:
            logger.exception("Structured decision call observer failed for {}", self.provider)

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
