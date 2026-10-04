"""Shared request, question, answer, and result types."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, cast

from .errors import DecisionProtocolError

JsonValue: TypeAlias = str | int | float | bool | None | list[Any] | dict[str, Any]
StructuredInput: TypeAlias = str | dict[str, JsonValue] | list[JsonValue]
CriterionDescription: TypeAlias = JsonValue


def validate_structured_input(value: object, field_name: str) -> None:
    """Validate a text, object, or array input containing only finite JSON values."""
    if isinstance(value, str):
        if not value.strip():
            raise DecisionProtocolError(f"{field_name} cannot be blank")
    elif not isinstance(value, (dict, list)):
        raise DecisionProtocolError(f"{field_name} must be text, an object, or an array")
    _validate_json_value(value, field_name)


def _validate_json_value(
    value: Any,
    field_name: str,
    active_containers: set[int] | None = None,
) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DecisionProtocolError(f"{field_name} contains a non-finite number")
        return
    if isinstance(value, list):
        active_list: set[int] = active_containers if active_containers is not None else set()
        container_value = cast(object, value)
        identity = id(container_value)
        if identity in active_list:
            raise DecisionProtocolError(f"{field_name} contains a circular value")
        active_list.add(identity)
        try:
            for index, item in enumerate(cast(list[Any], value)):
                _validate_json_value(item, f"{field_name}[{index}]", active_list)
        finally:
            active_list.remove(identity)
        return
    if isinstance(value, dict):
        active_dict: set[int] = active_containers if active_containers is not None else set()
        container_value = cast(object, value)
        identity = id(container_value)
        if identity in active_dict:
            raise DecisionProtocolError(f"{field_name} contains a circular value")
        active_dict.add(identity)
        try:
            for key, item in cast(dict[Any, Any], value).items():
                if not isinstance(key, str):
                    raise DecisionProtocolError(f"{field_name} object keys must be strings")
                _validate_json_value(item, field_name, active_dict)
        finally:
            active_dict.remove(identity)
        return
    raise DecisionProtocolError(f"{field_name} contains a value that is not JSON-compatible")


def _validate_criteria(criteria: Any, field_name: str) -> None:
    if not isinstance(criteria, dict):
        raise DecisionProtocolError(f"{field_name} must be an object")
    for key, description in cast(dict[Any, Any], criteria).items():
        if not isinstance(key, str) or not key.strip():
            raise DecisionProtocolError(f"{field_name} keys cannot be empty")
        _validate_json_value(description, f"{field_name} description")


@dataclass(frozen=True)
class DecisionUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class NoulQuestion:
    instructions: StructuredInput
    criteria: dict[str, CriterionDescription] | None = None
    type: Literal["noul"] = "noul"

    def validate(self) -> None:
        if self.type != "noul":
            raise DecisionProtocolError("Noul question type must be 'noul'")
        validate_structured_input(self.instructions, "Noul instructions")
        if self.criteria is None:
            return
        if set(self.criteria) != {"true", "false"}:
            raise DecisionProtocolError("Noul criteria must contain only true and false")
        _validate_criteria(self.criteria, "Noul criteria")


@dataclass(frozen=True)
class ChoiceQuestion:
    instructions: StructuredInput
    criteria: dict[str, CriterionDescription]
    type: Literal["choice"] = "choice"

    def validate(self) -> None:
        if self.type != "choice":
            raise DecisionProtocolError("Choice question type must be 'choice'")
        validate_structured_input(self.instructions, "Choice instructions")
        if not self.criteria:
            raise DecisionProtocolError("Choice questions require at least one criterion")
        _validate_criteria(self.criteria, "Choice criteria")


@dataclass(frozen=True)
class ScoreQuestion:
    instructions: StructuredInput
    criteria: Sequence[CriterionDescription]
    type: Literal["score"] = "score"

    def validate(self) -> None:
        if self.type != "score":
            raise DecisionProtocolError("Score question type must be 'score'")
        validate_structured_input(self.instructions, "Score instructions")
        criteria_value: Any = self.criteria
        if isinstance(criteria_value, (str, bytes)) or not isinstance(
            criteria_value, Sequence
        ):
            raise DecisionProtocolError("Score criteria must be an ordered sequence")
        criteria = cast(Sequence[CriterionDescription], criteria_value)
        if len(criteria) < 2:
            raise DecisionProtocolError("Score questions require at least two criteria")
        for index, description in enumerate(criteria):
            _validate_json_value(description, f"Score criteria[{index}]")


DecisionQuestion = NoulQuestion | ChoiceQuestion | ScoreQuestion


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


DecisionAnswer = NoulAnswer | ChoiceAnswer | ScoreAnswer


@dataclass(frozen=True)
class DecisionRequest:
    model: str
    state: StructuredInput
    questions: dict[str, DecisionQuestion]


@dataclass(frozen=True)
class DecisionResult:
    answers: dict[str, DecisionAnswer]
    model: str
    response_id: str | None = None
    usage: DecisionUsage | None = None
