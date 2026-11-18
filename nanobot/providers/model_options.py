"""Typed per-session model choices; None inherits configured defaults."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

CodexFastMode = bool | Literal["ultrafast"]

# Codex's published model support. Account/workspace eligibility is enforced upstream.
CODEX_ULTRAFAST_MODELS = ("gpt-6.2-astra", "gpt-6.2-sol", "gpt-6-astra", "gpt-6.1-sol")


def codex_supports_ultrafast(model: str) -> bool:
    model = model.strip().lower().removeprefix("openai-codex/").removeprefix("openai_codex/")
    return model in CODEX_ULTRAFAST_MODELS


class ModelOptionsPayload(TypedDict):
    reasoning_effort: str | None
    codex_fast_mode: CodexFastMode | None


@dataclass(frozen=True, slots=True)
class ModelOptions:
    reasoning_effort: str | None = None
    codex_fast_mode: CodexFastMode | None = None

    def to_dict(self) -> ModelOptionsPayload:
        return {
            "reasoning_effort": self.reasoning_effort,
            "codex_fast_mode": self.codex_fast_mode,
        }

    @classmethod
    def parse(cls, value: object) -> "ModelOptions":
        if not isinstance(value, Mapping):
            raise ValueError("model_options must be an object")
        data = cast(Mapping[object, object], value)
        if data.keys() - {"reasoning_effort", "codex_fast_mode"}:
            raise ValueError("model_options contains unknown options")
        effort = data.get("reasoning_effort")
        if effort is not None and (
            not isinstance(effort, str) or not effort or len(effort) > 256
            or effort.strip() != effort
            or any(ord(char) < 32 or ord(char) == 127 for char in effort)
        ):
            raise ValueError("reasoning_effort must be a non-empty string or null")
        fast = data.get("codex_fast_mode")
        if fast == "ultrafast":
            return cls(reasoning_effort=effort, codex_fast_mode="ultrafast")
        if fast is not None and not isinstance(fast, bool):
            raise ValueError('codex_fast_mode must be a boolean, "ultrafast", or null')
        return cls(reasoning_effort=effort, codex_fast_mode=fast)
