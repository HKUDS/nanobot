"""System One request serialization and response parsing."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from typing import Any, cast

import httpx

from .errors import (
    DecisionClientClosedError,
    DecisionHttpError,
    DecisionProtocolError,
    DecisionTimeoutError,
    DecisionTransportError,
    IncompleteDecisionResponseError,
    MalformedDecisionJsonError,
    MissingCredentialsError,
)
from .models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionAnswer,
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
    DecisionUsage,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)
from .providers import DecisionProviderSettings

# Keep at or below the provider's idle timeout; only decides reuse, not a background timer.
_DEFAULT_LIMITS = httpx.Limits(max_keepalive_connections=2, keepalive_expiry=30)


class SystemOneTransport:
    """Send and parse requests using the System One wire contract.

    The HTTP client is created on first use and reused until `aclose()`. The injected
    `transport` is owned by this object and closed with it. `aclose()` waits for
    evaluations already running to finish. Calls to `evaluate()` made after
    `aclose()` starts raise `DecisionClientClosedError`.
    """

    def __init__(
        self,
        *,
        provider_settings: DecisionProviderSettings,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.endpoint_url = provider_settings.endpoint_url
        self.api_key = provider_settings.api_key
        self.timeout = timeout
        self.proxy = provider_settings.proxy
        self.transport = transport
        self.requires_api_key = provider_settings.requires_api_key
        self._http_client: httpx.AsyncClient | None = None
        self._closed = False
        self._in_flight = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._close_lock = asyncio.Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    def _make_http_transport(self) -> httpx.AsyncBaseTransport:
        if self.transport is not None:
            return self.transport
        if self.proxy:
            return httpx.AsyncHTTPTransport(
                proxy=self.proxy,
                trust_env=False,
                limits=_DEFAULT_LIMITS,
            )
        return httpx.AsyncHTTPTransport(trust_env=False, limits=_DEFAULT_LIMITS)

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.timeout,
                transport=self._make_http_transport(),
                trust_env=False,
                follow_redirects=False,
            )
        return self._http_client

    async def aclose(self) -> None:
        """Wait for in-flight evaluations, then close the HTTP client and its transport."""
        self._closed = True
        async with self._close_lock:
            await self._idle.wait()
            client, self._http_client = self._http_client, None
            transport, self.transport = self.transport, None
            if client is not None:
                await client.aclose()
            elif transport is not None:
                await transport.aclose()

    async def evaluate(self, request: DecisionRequest) -> DecisionResult:
        if self._closed:
            raise DecisionClientClosedError("Decision client is closed")
        if self.requires_api_key and not self.api_key:
            raise MissingCredentialsError("API key is not configured for the selected provider")

        payload: dict[str, Any] = {
            "model": request.model,
            "state": request.state,
            "questions": {
                question_id: self._serialize_question(question)
                for question_id, question in request.questions.items()
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._in_flight += 1
        self._idle.clear()
        try:
            # Create the client on the first request, then reuse this instance's
            # client and connection pool for subsequent requests until aclose().
            response = await self._get_http_client().post(
                self.endpoint_url,
                headers=headers,
                content=json.dumps(payload, separators=(",", ":"), allow_nan=False),
            )
        except httpx.TimeoutException as exc:
            raise DecisionTimeoutError("Decision request timed out") from exc
        except httpx.TransportError as exc:
            raise DecisionTransportError("Decision transport failed") from exc
        except Exception as exc:
            raise DecisionTransportError("Decision request failed") from exc
        finally:
            self._in_flight -= 1
            if self._in_flight == 0:
                self._idle.set()

        if not 200 <= response.status_code < 300:
            raise DecisionHttpError(response.status_code)

        try:
            data = response.json()
        except ValueError as exc:
            raise MalformedDecisionJsonError("Decision response is not valid JSON") from exc

        return self._parse_result(data, request.questions)

    @staticmethod
    def _serialize_question(question: DecisionQuestion) -> dict[str, Any]:
        if isinstance(question, NoulQuestion):
            serialized: dict[str, Any] = {
                "type": "noul",
                "instructions": question.instructions,
            }
            if question.criteria is not None:
                serialized["criteria"] = {
                    "true": question.criteria["true"],
                    "false": question.criteria["false"],
                }
            return serialized
        if isinstance(question, ChoiceQuestion):
            return {
                "type": "choice",
                "instructions": question.instructions,
                "criteria": dict(question.criteria),
            }
        return {
            "type": "score",
            "instructions": question.instructions,
            "criteria": list(question.criteria),
        }

    @staticmethod
    def _is_finite_number(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )

    @classmethod
    def _parse_result(
        cls,
        data: Any,
        requested_questions: Mapping[str, DecisionQuestion],
    ) -> DecisionResult:
        if not isinstance(data, Mapping):
            raise DecisionProtocolError("Response root must be an object")
        payload = cast(Mapping[str, Any], data)
        answers_value = payload.get("answers")
        if not isinstance(answers_value, Mapping):
            raise IncompleteDecisionResponseError("Response answers missing")

        answers_payload = cast(Mapping[str, Any], answers_value)
        requested_ids = set(requested_questions)
        actual_ids = set(answers_payload)
        # Ensure every requested question ID is present in the response
        if not requested_ids.issubset(actual_ids):
            raise IncompleteDecisionResponseError("Missing requested answers")
        if actual_ids - requested_ids:
            raise DecisionProtocolError("Unexpected answer IDs returned")

        answers: dict[str, DecisionAnswer] = {}
        for question_id, question in requested_questions.items():
            raw_answer = answers_payload.get(question_id)
            if raw_answer is None or not isinstance(raw_answer, Mapping):
                raise IncompleteDecisionResponseError(f"Answer {question_id!r} missing")
            answer_map = cast(Mapping[str, Any], raw_answer)
            # Ensure the answer type matches the question type
            if answer_map.get("type") != question.type:
                raise DecisionProtocolError(f"Answer type mismatch for {question_id!r}")

            # Dispatch parsing logic based on the question type
            if isinstance(question, NoulQuestion):
                answers[question_id] = cls._parse_noul_answer(answer_map, question_id)
            elif isinstance(question, ChoiceQuestion):
                answers[question_id] = cls._parse_choice_answer(
                    answer_map,
                    question,
                    question_id,
                )
            else:
                answers[question_id] = cls._parse_score_answer(
                    answer_map,
                    question,
                    question_id,
                )

        return cls._parse_result_metadata(payload, answers)

    @classmethod
    def _parse_noul_answer(
        cls,
        answer: Mapping[str, Any],
        question_id: str,
    ) -> NoulAnswer:
        value = answer.get("noul")
        if value is None or not cls._is_finite_number(value):
            raise DecisionProtocolError(f"Noul value for {question_id!r} is invalid")
        numeric_value = float(value)
        if not 0.0 <= numeric_value <= 1.0:
            raise DecisionProtocolError(f"Noul value for {question_id!r} is invalid")
        return NoulAnswer(type="noul", noul=numeric_value)

    @classmethod
    def _parse_choice_answer(
        cls,
        answer: Mapping[str, Any],
        question: ChoiceQuestion,
        question_id: str,
    ) -> ChoiceAnswer:
        choice = answer.get("choice")
        probabilities = answer.get("probabilities")
        confidence = answer.get("confidence")
        if not isinstance(choice, str) or choice not in question.criteria:
            raise DecisionProtocolError(f"Choice answer for {question_id!r} is invalid")
        if not isinstance(probabilities, Mapping):
            raise DecisionProtocolError(f"Choice probabilities for {question_id!r} are invalid")

        probability_map = cast(Mapping[str, Any], probabilities)
        # Ensure probability keys match the question criteria
        if set(probability_map) != set(question.criteria):
            raise DecisionProtocolError(
                f"Choice probability keys for {question_id!r} do not match criteria"
            )
        probability_values = cls._parse_probabilities(
            probability_map,
            question_id,
            "Choice",
        )
        confidence_value = cls._parse_confidence(confidence, question_id, "Choice")
        return ChoiceAnswer(
            type="choice",
            choice=choice,
            probabilities=probability_values,
            confidence=confidence_value,
        )

    @classmethod
    def _parse_score_answer(
        cls,
        answer: Mapping[str, Any],
        question: ScoreQuestion,
        question_id: str,
    ) -> ScoreAnswer:
        score = answer.get("score")
        legend = answer.get("legend")
        probabilities = answer.get("probabilities")
        confidence = answer.get("confidence")
        if score is None or not cls._is_finite_number(score):
            raise DecisionProtocolError(f"Score value for {question_id!r} is invalid")
        score_value = float(score)
        if not 0.0 <= score_value <= len(question.criteria) - 1:
            raise DecisionProtocolError(f"Score value for {question_id!r} is invalid")

        # Note: Keys in 'legend' and 'probabilities' are stringified 0-based indices ("0", "1", ...)
        # corresponding to the sequence of options defined in question.criteria.
        expected_keys = {str(index) for index in range(len(question.criteria))}
        if not isinstance(legend, Mapping):
            raise DecisionProtocolError(f"Score legend for {question_id!r} is invalid")

        legend_map = cast(Mapping[str, Any], legend)
        if set(legend_map) != expected_keys:
            raise DecisionProtocolError(
                f"Score legend keys for {question_id!r} do not match criteria"
            )
        if any(not isinstance(value, str) for value in legend_map.values()):
            raise DecisionProtocolError(f"Score legend for {question_id!r} is invalid")
        if not isinstance(probabilities, Mapping):
            raise DecisionProtocolError(f"Score probabilities for {question_id!r} are invalid")

        probability_map = cast(Mapping[str, Any], probabilities)
        if set(probability_map) != expected_keys:
            raise DecisionProtocolError(
                f"Score probability keys for {question_id!r} do not match legend"
            )
        probability_values = cls._parse_probabilities(
            probability_map,
            question_id,
            "Score",
        )
        confidence_value = cls._parse_confidence(confidence, question_id, "Score")
        return ScoreAnswer(
            type="score",
            score=score_value,
            legend=dict(legend_map),
            probabilities=probability_values,
            confidence=confidence_value,
        )

    @classmethod
    def _parse_probabilities(
        cls,
        probabilities: Mapping[str, Any],
        question_id: str,
        question_type: str,
    ) -> dict[str, float]:
        values: dict[str, float] = {}
        for key, value in probabilities.items():
            if value is None or not cls._is_finite_number(value):
                raise DecisionProtocolError(
                    f"{question_type} probability for {question_id!r} is invalid"
                )
            numeric_value = float(value)
            if numeric_value < 0:
                raise DecisionProtocolError(
                    f"{question_type} probability for {question_id!r} is invalid"
                )
            values[str(key)] = numeric_value
        if not math.isclose(sum(values.values()), 1.0, abs_tol=1e-6):
            raise DecisionProtocolError(
                f"{question_type} probabilities for {question_id!r} do not sum to 1"
            )
        return values

    @classmethod
    def _parse_confidence(cls, value: Any, question_id: str, question_type: str) -> float:
        if value is None or not cls._is_finite_number(value):
            raise DecisionProtocolError(
                f"{question_type} confidence for {question_id!r} is invalid"
            )
        confidence = float(value)
        if not 0.0 <= confidence <= 1.0:
            raise DecisionProtocolError(
                f"{question_type} confidence for {question_id!r} is invalid"
            )
        return confidence

    @classmethod
    def _parse_result_metadata(
        cls,
        payload: Mapping[str, Any],
        answers: dict[str, DecisionAnswer],
    ) -> DecisionResult:
        response_id = payload.get("id")
        if response_id is not None and (
            not isinstance(response_id, str) or not response_id.strip()
        ):
            raise DecisionProtocolError("Response id is invalid")
        model = payload.get("model")
        if not isinstance(model, str) or not model.strip():
            raise IncompleteDecisionResponseError("Missing response model")
        usage = payload.get("usage")
        decision_usage = None
        if usage is not None:
            if not isinstance(usage, Mapping):
                raise DecisionProtocolError("Response usage is invalid")
            usage_map = cast(Mapping[str, Any], usage)
            input_tokens = cls._parse_optional_token_count(
                usage_map.get("input_tokens"), "input_tokens"
            )
            output_tokens = cls._parse_optional_token_count(
                usage_map.get("output_tokens"), "output_tokens"
            )
            decision_usage = DecisionUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        return DecisionResult(
            answers=answers,
            response_id=response_id,
            model=model,
            usage=decision_usage,
        )

    @staticmethod
    def _parse_optional_token_count(value: Any, field_name: str) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise DecisionProtocolError(f"Response usage {field_name} is invalid")
        return value
