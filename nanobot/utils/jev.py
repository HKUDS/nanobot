from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx


class JevError(Exception):
    """Base error for all JEV failures."""


class JevMissingCredentialsError(JevError):
    """Raised when the OpenRouter JEV key is absent."""


class JevHttpError(JevError):
    """Raised when the JEV endpoint returns an HTTP error."""

    def __init__(self, status_code: int | None, reason: str | None = None):
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"HTTP {status_code} {reason or ''}".strip())


class JevTransportError(JevError):
    """Raised when the underlying async transport fails."""


class JevTimeoutError(JevError):
    """Raised when the JEV request times out."""


class JevMalformedJsonError(JevError):
    """Raised when the response body is not valid JSON."""


class JevProtocolError(JevError):
    """Raised when the response protocol is invalid or incomplete."""


class JevIncompleteResponseError(JevProtocolError):
    """Raised when a response is missing required data."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost: float


@dataclass(frozen=True)
class NoulQuestion:
    instructions: str
    criteria: dict[str, str]
    type: Literal["noul"] = "noul"

    def validate(self) -> None:
        if not self.instructions or not self.instructions.strip():
            raise JevProtocolError("Noul instructions cannot be empty")
        if set(self.criteria) != {"true", "false"}:
            raise JevProtocolError("Noul criteria must contain only true and false")


@dataclass(frozen=True)
class ChoiceQuestion:
    instructions: str
    criteria: dict[str, str]
    type: Literal["choice"] = "choice"

    def validate(self) -> None:
        if not self.instructions or not self.instructions.strip():
            raise JevProtocolError("Choice instructions cannot be empty")
        if not self.criteria:
            raise JevProtocolError("Choice questions require at least one criterion")


@dataclass(frozen=True)
class ScoreQuestion:
    instructions: str
    criteria: Sequence[str]
    type: Literal["score"] = "score"

    def validate(self) -> None:
        if not self.instructions or not self.instructions.strip():
            raise JevProtocolError("Score instructions cannot be empty")
        if len(self.criteria) < 2:
            raise JevProtocolError("Score questions require at least two criteria")


JevQuestion = NoulQuestion | ChoiceQuestion | ScoreQuestion


@dataclass(frozen=True)
class NoulAnswer:
    type: Literal["noul"]
    noul: float


@dataclass(frozen=True)
class ChoiceAnswer:
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float]
    confidence: float


@dataclass(frozen=True)
class ScoreAnswer:
    type: Literal["score"]
    score: float
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float


JevAnswer = NoulAnswer | ChoiceAnswer | ScoreAnswer


@dataclass(frozen=True)
class JevRequest:
    model: str
    state: str
    questions: dict[str, JevQuestion]


@dataclass(frozen=True)
class JevResult:
    answers: dict[str, JevAnswer]
    response_id: str
    model: str
    provider: str
    usage: Usage


class JevClient:
    """Small async client for the OpenRouter Decisions API."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        timeout: float,
        proxy: str | None = None,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not model or not model.strip():
            raise JevProtocolError("Model cannot be empty")
        if timeout <= 0 or timeout > 120:
            raise ValueError("JEV timeout must be within (0, 120]")

        self.model = model
        resolved_key = (api_key or os.environ.get("OPENROUTER_API_KEY") or "").strip()
        self.api_key = resolved_key
        self.timeout = float(timeout)
        self.proxy = proxy
        self.transport = transport

    @staticmethod
    def _validate_question_id(question_id: str) -> None:
        if not question_id or not question_id.strip():
            raise JevProtocolError("Question ID cannot be empty")

    @staticmethod
    def _validate_model(model: str) -> None:
        if not model or not model.strip():
            raise JevProtocolError("Model cannot be empty")

    @staticmethod
    def _validate_state(state: str) -> None:
        if not isinstance(state, str):
            raise JevProtocolError("State must be a string")

    @staticmethod
    def _coerce_question_map(
        questions: Mapping[str, JevQuestion],
    ) -> dict[str, JevQuestion]:
        out: dict[str, JevQuestion] = {}
        for question_id, question in questions.items():
            JevClient._validate_question_id(question_id)
            if not isinstance(question, (NoulQuestion, ChoiceQuestion, ScoreQuestion)):
                raise JevProtocolError(f"Unsupported question type for {question_id!r}")
            question.validate()
            out[question_id] = question
        return out

    @staticmethod
    def _serialize_question(question: JevQuestion) -> dict[str, Any]:
        if isinstance(question, NoulQuestion):
            return {
                "type": "noul",
                "instructions": question.instructions,
                "criteria": {"true": question.criteria["true"], "false": question.criteria["false"]},
            }
        if isinstance(question, ChoiceQuestion):
            return {
                "type": "choice",
                "instructions": question.instructions,
                "criteria": dict(question.criteria),
            }
        if isinstance(question, ScoreQuestion):
            criteria = list(question.criteria)
            return {
                "type": "score",
                "instructions": question.instructions,
                "criteria": criteria,
            }
        raise JevProtocolError("Unsupported question type")

    def _build_request(self, *, state: str, questions: Mapping[str, JevQuestion]) -> JevRequest:
        self._validate_model(self.model)
        self._validate_state(state)
        validated = self._coerce_question_map(questions)
        return JevRequest(model=self.model, state=state, questions=validated)

    def _make_transport(self) -> httpx.BaseTransport | httpx.AsyncBaseTransport | None:
        if self.transport is not None:
            return self.transport
        if self.proxy:
            return httpx.AsyncHTTPTransport(proxy=self.proxy, trust_env=False)
        return httpx.AsyncHTTPTransport(trust_env=False)

    async def decide(
        self,
        *,
        state: str,
        questions: Mapping[str, JevQuestion],
    ) -> JevResult:
        if not self.api_key or not self.api_key.strip():
            raise JevMissingCredentialsError("OpenRouter API key is not configured")

        request = self._build_request(state=state, questions=questions)
        payload = {
            "model": request.model,
            "state": request.state,
            "questions": {
                question_id: self._serialize_question(question)
                for question_id, question in request.questions.items()
            },
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self._make_transport(),
                trust_env=False,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    "https://openrouter.ai/api/alpha/decisions",
                    headers=headers,
                    content=json.dumps(payload, separators=(",", ":")),
                )
        except httpx.TimeoutException as exc:
            raise JevTimeoutError("JEV request timed out") from exc
        except httpx.TransportError as exc:
            raise JevTransportError("JEV transport failed") from exc
        except Exception as exc:
            raise JevTransportError("JEV request failed") from exc

        if response.status_code >= 400:
            raise JevHttpError(response.status_code)

        try:
            data = response.json()
        except ValueError as exc:
            raise JevMalformedJsonError("JEV response is not valid JSON") from exc

        return self._parse_result(data, request.questions)

    @staticmethod
    def _is_finite_number(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )

    @classmethod
    def _parse_result(cls, data: Any, requested_questions: Mapping[str, JevQuestion]) -> JevResult:
        if not isinstance(data, Mapping):
            raise JevProtocolError("Response root must be an object")
        if "answers" not in data or not isinstance(data["answers"], Mapping):
            raise JevIncompleteResponseError("Response answers missing")

        requested_ids = set(requested_questions)
        actual_ids = set(data["answers"].keys())
        if not requested_ids.issubset(actual_ids):
            raise JevIncompleteResponseError("Missing requested answers")
        if actual_ids - requested_ids:
            raise JevProtocolError("Unexpected answer IDs returned")

        answers: dict[str, JevAnswer] = {}
        for question_id, question in requested_questions.items():
            raw_answer = data["answers"].get(question_id)
            if raw_answer is None or not isinstance(raw_answer, Mapping):
                raise JevIncompleteResponseError(f"Answer {question_id!r} missing")
            if raw_answer.get("type") != question.type:
                raise JevProtocolError(f"Answer type mismatch for {question_id!r}")
            if isinstance(question, NoulQuestion):
                value = raw_answer.get("noul")
                if not cls._is_finite_number(value) or not (0.0 <= float(value) <= 1.0):
                    raise JevProtocolError(f"Noul value for {question_id!r} is invalid")
                answers[question_id] = NoulAnswer(type="noul", noul=float(value))
            elif isinstance(question, ChoiceQuestion):
                choice = raw_answer.get("choice")
                probs = raw_answer.get("probabilities")
                confidence = raw_answer.get("confidence")
                if not isinstance(choice, str) or choice not in question.criteria:
                    raise JevProtocolError(f"Choice answer for {question_id!r} is invalid")
                if not isinstance(probs, Mapping):
                    raise JevProtocolError(f"Choice probabilities for {question_id!r} are invalid")
                if set(probs.keys()) != set(question.criteria.keys()):
                    raise JevProtocolError(f"Choice probability keys for {question_id!r} do not match criteria")
                total = 0.0
                for key, value in probs.items():
                    if not cls._is_finite_number(value) or float(value) < 0:
                        raise JevProtocolError(f"Choice probability for {question_id!r} is invalid")
                    total += float(value)
                if not math.isclose(total, 1.0, abs_tol=1e-6):
                    raise JevProtocolError(f"Choice probabilities for {question_id!r} do not sum to 1")
                if not cls._is_finite_number(confidence) or not (0.0 <= float(confidence) <= 1.0):
                    raise JevProtocolError(f"Choice confidence for {question_id!r} is invalid")
                answers[question_id] = ChoiceAnswer(
                    type="choice",
                    choice=choice,
                    probabilities={str(k): float(v) for k, v in probs.items()},
                    confidence=float(confidence),
                )
            elif isinstance(question, ScoreQuestion):
                score = raw_answer.get("score")
                legend = raw_answer.get("legend")
                probs = raw_answer.get("probabilities")
                confidence = raw_answer.get("confidence")
                if not cls._is_finite_number(score) or not (0.0 <= float(score) <= len(question.criteria) - 1):
                    raise JevProtocolError(f"Score value for {question_id!r} is invalid")
                if not isinstance(legend, Mapping):
                    raise JevProtocolError(f"Score legend for {question_id!r} is invalid")
                expected_legend_keys = {str(i) for i in range(len(question.criteria))}
                if set(legend.keys()) != expected_legend_keys:
                    raise JevProtocolError(f"Score legend keys for {question_id!r} do not match criteria")
                if not isinstance(probs, Mapping):
                    raise JevProtocolError(f"Score probabilities for {question_id!r} are invalid")
                if set(probs.keys()) != expected_legend_keys:
                    raise JevProtocolError(f"Score probability keys for {question_id!r} do not match legend")
                total = 0.0
                for key, value in probs.items():
                    if not cls._is_finite_number(value) or float(value) < 0:
                        raise JevProtocolError(f"Score probability for {question_id!r} is invalid")
                    total += float(value)
                if not math.isclose(total, 1.0, abs_tol=1e-6):
                    raise JevProtocolError(f"Score probabilities for {question_id!r} do not sum to 1")
                if not cls._is_finite_number(confidence) or not (0.0 <= float(confidence) <= 1.0):
                    raise JevProtocolError(f"Score confidence for {question_id!r} is invalid")
                answers[question_id] = ScoreAnswer(
                    type="score",
                    score=float(score),
                    legend={str(k): str(v) for k, v in legend.items()},
                    probabilities={str(k): float(v) for k, v in probs.items()},
                    confidence=float(confidence),
                )
            else:
                raise JevProtocolError(f"Unsupported answer type for {question_id!r}")

        response_id = data.get("id")
        if not isinstance(response_id, str) or not response_id.strip():
            raise JevIncompleteResponseError("Missing response id")
        model = data.get("model")
        if not isinstance(model, str) or not model.strip():
            raise JevIncompleteResponseError("Missing response model")
        provider = data.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise JevIncompleteResponseError("Missing response provider")
        usage = data.get("usage")
        if not isinstance(usage, Mapping):
            raise JevIncompleteResponseError("Missing usage metadata")
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        cost = usage.get("cost")
        if not isinstance(input_tokens, int) or isinstance(input_tokens, bool) or input_tokens < 0:
            raise JevIncompleteResponseError("Usage input_tokens missing or invalid")
        if not isinstance(output_tokens, int) or isinstance(output_tokens, bool) or output_tokens < 0:
            raise JevIncompleteResponseError("Usage output_tokens missing or invalid")
        if not cls._is_finite_number(cost) or float(cost) < 0:
            raise JevIncompleteResponseError("Usage cost missing or invalid")

        return JevResult(
            answers=answers,
            response_id=response_id,
            model=model,
            provider=provider,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=float(cost),
            ),
        )


async def decide(
    *,
    model: str,
    api_key: str | None,
    state: str,
    questions: Mapping[str, JevQuestion],
    timeout: float = 15.0,
    proxy: str | None = None,
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
) -> JevResult:
    """Compatibility helper for JEV requests."""
    client = JevClient(
        model=model,
        api_key=api_key,
        timeout=timeout,
        proxy=proxy,
        transport=transport,
    )
    return await client.decide(state=state, questions=questions)
