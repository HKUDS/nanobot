"""DSPy SkillModule wrapper that optimizes SKILL.md body, not wrapper docstrings (E4-D2)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from nanobot.agent.evolution.deps import require_evolution_extra

_FRONTMATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_DESC_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE | re.IGNORECASE)

PREDICTOR_ATTR = "skill_executor"
_SIGNATURE = "query, tool_context -> suggested_actions"

ERR_MISSING_FRONTMATTER = "missing YAML frontmatter"
ERR_NAME_MISMATCH = "frontmatter name mismatch"


@dataclass(frozen=True, slots=True)
class SkillMdParts:
    """Split view of a SKILL.md file."""

    frontmatter: str
    body: str
    skill_name: str
    description: str


@dataclass(frozen=True, slots=True)
class GepaSkillState:
    """Frozen frontmatter plus mutable SKILL.md body for GEPA."""

    frontmatter: str
    body: str
    skill_name: str
    description: str

    def with_body(self, body: str) -> GepaSkillState:
        return replace(self, body=body)

    def to_skill_md(self) -> str:
        return merge_skill_md(self.frontmatter, self.body)


class GepaSkillModule:
    """Bridge an active skill file to a DSPy module with body-only optimization."""

    def __init__(self, state: GepaSkillState) -> None:
        self._state = state
        self._dspy_module: Any | None = None

    @property
    def skill_name(self) -> str:
        return self._state.skill_name

    @property
    def description(self) -> str:
        return self._state.description

    @property
    def frontmatter(self) -> str:
        return self._state.frontmatter

    @property
    def body(self) -> str:
        return self._state.body

    @body.setter
    def body(self, value: str) -> None:
        self._state = self._state.with_body(value)
        if self._dspy_module is not None:
            _set_predictor_instructions(self._dspy_module, value)

    @classmethod
    def from_skill_md(
        cls,
        content: str,
        *,
        expected_name: str | None = None,
    ) -> GepaSkillModule:
        parts = split_skill_md(content)
        if expected_name and parts.skill_name != expected_name:
            raise ValueError(f"{ERR_NAME_MISMATCH} (expected {expected_name}, got {parts.skill_name})")
        return cls(
            GepaSkillState(
                frontmatter=parts.frontmatter,
                body=parts.body,
                skill_name=parts.skill_name,
                description=parts.description,
            )
        )

    @classmethod
    def from_path(cls, path: Path, *, expected_name: str | None = None) -> GepaSkillModule:
        return cls.from_skill_md(path.read_text(encoding="utf-8"), expected_name=expected_name)

    @classmethod
    def from_active_skill(cls, workspace: Path, skill_name: str) -> GepaSkillModule:
        skill_path = workspace.expanduser().resolve() / "skills" / skill_name / "SKILL.md"
        if not skill_path.is_file():
            raise FileNotFoundError(f"active skill not found: {skill_path}")
        return cls.from_path(skill_path, expected_name=skill_name)

    def to_skill_md(self) -> str:
        return self._state.to_skill_md()

    def sync_from_dspy_module(self, module: Any) -> None:
        """Copy optimized instructions back into local body state."""
        self._state = self._state.with_body(extract_body_from_dspy_module(module))

    def build_dspy_module(self) -> Any:
        """Create a DSPy module whose optimizable text is the SKILL.md body."""
        missing = require_evolution_extra()
        if missing:
            raise RuntimeError(missing)

        import dspy

        instructions = self._state.body

        class _SkillPredictorModule(dspy.Module):
            # Intentionally no class docstring: GEPA must mutate signature instructions,
            # not wrapper docstrings (Hermes self-evolution #38).

            def __init__(self, skill_instructions: str) -> None:
                super().__init__()
                signature = dspy.Signature(_SIGNATURE, instructions=skill_instructions)
                setattr(self, PREDICTOR_ATTR, dspy.Predict(signature))

        module = _SkillPredictorModule(instructions)
        self._dspy_module = module
        return module


def split_skill_md(content: str) -> SkillMdParts:
    """Split SKILL.md into frozen frontmatter and optimizable body."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(ERR_MISSING_FRONTMATTER)

    frontmatter = match.group(1).strip("\n")
    body = content[match.end() :].strip("\n")
    name_match = _NAME_RE.search(frontmatter)
    desc_match = _DESC_RE.search(frontmatter)
    if name_match is None:
        raise ValueError("frontmatter missing name")
    if desc_match is None:
        raise ValueError("frontmatter missing description")

    return SkillMdParts(
        frontmatter=frontmatter,
        body=body,
        skill_name=name_match.group(1).strip(),
        description=desc_match.group(1).strip(),
    )


def merge_skill_md(frontmatter: str, body: str) -> str:
    """Rebuild SKILL.md while preserving the original frontmatter block."""
    normalized_body = body.strip("\n")
    if normalized_body:
        normalized_body = f"{normalized_body}\n"
    return f"---\n{frontmatter.strip()}\n---\n\n{normalized_body}"


def extract_body_from_dspy_module(module: Any) -> str:
    """Read optimized SKILL.md body from predictor signature instructions."""
    predictor = getattr(module, PREDICTOR_ATTR, None)
    if predictor is None:
        raise ValueError(f"dspy module missing {PREDICTOR_ATTR!r} predictor")
    instructions = getattr(getattr(predictor, "signature", None), "instructions", None)
    return str(instructions or "").strip()


def _set_predictor_instructions(module: Any, instructions: str) -> None:
    predictor = getattr(module, PREDICTOR_ATTR, None)
    if predictor is None:
        return
    signature = getattr(predictor, "signature", None)
    if signature is None or not hasattr(signature, "with_instructions"):
        return
    predictor.signature = signature.with_instructions(instructions)
