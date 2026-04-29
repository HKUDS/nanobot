"""Skill Orchestrator for intelligent skill selection based on user input.

This module provides a lightweight orchestrator that:
1. Analyzes user input to select relevant skills
2. Supports metadata triggers and related tools for better matching
3. Records selection decisions for debugging and analysis
4. Validates skill quality and emits warnings for issues
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.skills import SkillsLoader
    from nanobot.agent.tools.registry import ToolRegistry


def _is_chinese_char(c: str) -> bool:
    """Check if a character is a Chinese character."""
    code = ord(c)
    return (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF)


def _detect_language(text: str) -> str:
    """Detect if text is primarily Chinese or English.

    Returns: 'zh' if mostly Chinese, 'en' otherwise.
    """
    if not text:
        return "en"
    chinese_chars = sum(1 for c in text if _is_chinese_char(c))
    total_chars = sum(1 for c in text if c.isalnum())
    if total_chars == 0:
        return "en"
    ratio = chinese_chars / total_chars
    return "zh" if ratio > 0.3 else "en"


def _tokenize(text: str) -> list[str]:
    """Tokenize text for keyword matching.

    For Chinese: extract individual characters as tokens.
    For English: split by word boundaries, lowercase.
    """
    if not text:
        return []

    lang = _detect_language(text)
    tokens: list[str] = []

    if lang == "zh":
        tokens = [c for c in text if _is_chinese_char(c)]
    else:
        words = re.findall(r"\b\w+\b", text.lower())
        tokens = [w for w in words if len(w) > 2]

    return tokens


def _compute_jaccard_similarity(tokens1: list[str], tokens2: list[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not tokens1 or not tokens2:
        return 0.0
    set1 = set(tokens1)
    set2 = set(tokens2)
    intersection = set1 & set2
    union = set1 | set2
    return len(intersection) / len(union) if union else 0.0


@dataclasses.dataclass
class SkillCandidate:
    """A candidate skill with matching metadata."""

    name: str
    path: str
    description: str = ""
    triggers: list[str] = dataclasses.field(default_factory=list)
    related_tools: list[str] = dataclasses.field(default_factory=list)
    score: float = 0.0
    match_reason: str = ""
    is_always: bool = False
    is_available: bool = True
    validation_warnings: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class SkillSkipped:
    """A skill that was skipped with reason."""

    name: str
    reason: str
    score: float = 0.0


@dataclasses.dataclass
class SkillSelectionRecord:
    """Structured record of skill selection for a turn.

    This record captures:
    - Which skills were considered and why
    - Which skills were selected for injection
    - Which skills were skipped and why
    - Which tools were used in this turn
    - Any warnings encountered
    """

    user_input: str = ""
    enabled: bool = False
    max_skills: int = 3
    candidates: list[SkillCandidate] = dataclasses.field(default_factory=list)
    selected: list[str] = dataclasses.field(default_factory=list)
    skipped: list[SkillSkipped] = dataclasses.field(default_factory=list)
    tools_used: list[str] = dataclasses.field(default_factory=list)
    status: str = "initialized"
    warnings: list[str] = dataclasses.field(default_factory=list)
    always_skills: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dict."""
        return {
            "user_input": self.user_input,
            "enabled": self.enabled,
            "max_skills": self.max_skills,
            "candidates": [
                {
                    "name": c.name,
                    "path": c.path,
                    "description": c.description,
                    "triggers": c.triggers,
                    "related_tools": c.related_tools,
                    "score": c.score,
                    "match_reason": c.match_reason,
                    "is_always": c.is_always,
                    "is_available": c.is_available,
                    "validation_warnings": c.validation_warnings,
                }
                for c in self.candidates
            ],
            "selected": self.selected,
            "skipped": [{"name": s.name, "reason": s.reason, "score": s.score} for s in self.skipped],
            "tools_used": self.tools_used,
            "status": self.status,
            "warnings": self.warnings,
            "always_skills": self.always_skills,
        }


class SkillOrchestrator:
    """Lightweight skill orchestrator for intelligent skill selection.

    The orchestrator:
    1. Collects all available skills with their metadata
    2. Validates skill quality (empty content, encoding issues, invalid tool references)
    3. Scores skills based on user input matching
    4. Selects top-k skills for injection
    5. Records all decisions for debugging

    Matching priority (highest to lowest):
    1. Exact trigger word match in user input
    2. Related tool keyword match
    3. Description similarity match
    """

    _TRIGGER_WEIGHT = 1.0
    _TOOL_WEIGHT = 0.7
    _DESCRIPTION_WEIGHT = 0.5
    _NAME_WEIGHT = 0.3

    def __init__(
        self,
        skills_loader: SkillsLoader,
        enabled: bool = False,
        max_skills: int = 3,
    ) -> None:
        """Initialize the skill orchestrator.

        Args:
            skills_loader: The SkillsLoader instance to use.
            enabled: Whether orchestration is enabled (default: False for backward compatibility).
            max_skills: Maximum number of skills to inject per turn (excluding always skills).
        """
        self._loader = skills_loader
        self._enabled = enabled
        self._max_skills = max(max_skills, 1)
        self._last_record: SkillSelectionRecord | None = None

    @property
    def enabled(self) -> bool:
        """Whether orchestration is enabled."""
        return self._enabled

    @property
    def last_record(self) -> SkillSelectionRecord | None:
        """Get the last selection record for debugging."""
        return self._last_record

    def _validate_skill_content(self, name: str, content: str | None) -> list[str]:
        """Validate skill content and return warnings if issues found.

        Checks:
        1. Empty content after stripping frontmatter
        2. Potential encoding issues (garbled characters)
        """
        warnings: list[str] = []

        if content is None:
            warnings.append(f"Skill '{name}': content is None")
            return warnings

        from nanobot.agent.skills import SkillsLoader

        class _TempLoader(SkillsLoader):
            @staticmethod
            def strip(content: str) -> str:
                return _TempLoader._strip_frontmatter(_TempLoader, content)

        stripped = _TempLoader._strip_frontmatter(_TempLoader(Path("/fake")), content).strip()

        if not stripped:
            warnings.append(f"Skill '{name}': empty content after frontmatter")

        if self._detect_garbled_content(stripped):
            warnings.append(f"Skill '{name}': possible encoding issues detected")

        return warnings

    def _detect_garbled_content(self, text: str) -> bool:
        """Detect potential encoding issues or garbled text.

        Looks for patterns like:
        - Multiple consecutive replacement characters (ï¿½, etc.)
        - Unusually high ratio of non-ASCII, non-Chinese characters
        """
        if not text:
            return False

        replacement_chars = 0
        unusual_chars = 0
        total_chars = len(text)

        for c in text:
            code = ord(c)
            if 0xFFFD <= code <= 0xFFFF or 0x0080 <= code <= 0x009F:
                replacement_chars += 1
            elif not (
                (0x0020 <= code <= 0x007E) or _is_chinese_char(c) or c in "\n\r\t"
            ):
                unusual_chars += 1

        if total_chars == 0:
            return False

        if replacement_chars > 3:
            return True
        if unusual_chars / total_chars > 0.3:
            return True

        return False

    def _validate_related_tools(
        self, name: str, related_tools: list[str], tool_registry: ToolRegistry | None
    ) -> list[str]:
        """Validate that referenced tools exist in the registry.

        Returns warnings for tools that don't exist.
        """
        warnings: list[str] = []
        if not related_tools or tool_registry is None:
            return warnings

        for tool in related_tools:
            if not tool_registry.has(tool):
                warnings.append(f"Skill '{name}': references unknown tool '{tool}'")

        return warnings

    def _extract_candidates(
        self, tool_registry: ToolRegistry | None = None
    ) -> tuple[list[SkillCandidate], list[str]]:
        """Extract all skill candidates with metadata and validation.

        Returns: (candidates, global_warnings)
        """
        candidates: list[SkillCandidate] = []
        global_warnings: list[str] = []

        all_skills = self._loader.list_skills(filter_unavailable=False)
        always_skills = set(self._loader.get_always_skills())

        for entry in all_skills:
            name = entry["name"]
            path = entry["path"]

            meta = self._loader.get_skill_metadata(name) or {}
            desc = self._loader._get_skill_description(name)

            nanobot_meta = self._loader._get_skill_meta(name)

            triggers: list[str] = []
            if "triggers" in nanobot_meta:
                triggers = nanobot_meta["triggers"] if isinstance(nanobot_meta["triggers"], list) else []
            elif "triggers" in meta:
                triggers = meta["triggers"] if isinstance(meta["triggers"], list) else []

            related_tools: list[str] = []
            if "related_tools" in nanobot_meta:
                related_tools = nanobot_meta["related_tools"] if isinstance(nanobot_meta["related_tools"], list) else []
            elif "relatedTools" in nanobot_meta:
                related_tools = nanobot_meta["relatedTools"] if isinstance(nanobot_meta["relatedTools"], list) else []
            elif "related_tools" in meta:
                related_tools = meta["related_tools"] if isinstance(meta["related_tools"], list) else []
            elif "relatedTools" in meta:
                related_tools = meta["relatedTools"] if isinstance(meta["relatedTools"], list) else []

            is_always = name in always_skills
            is_available = self._loader._check_requirements(nanobot_meta)

            validation_warnings: list[str] = []

            content = self._loader.load_skill(name)
            validation_warnings.extend(self._validate_skill_content(name, content))

            validation_warnings.extend(self._validate_related_tools(name, related_tools, tool_registry))

            candidate = SkillCandidate(
                name=name,
                path=path,
                description=desc,
                triggers=triggers,
                related_tools=related_tools,
                is_always=is_always,
                is_available=is_available,
                validation_warnings=validation_warnings,
            )

            for warning in validation_warnings:
                logger.warning(warning)
                global_warnings.append(warning)

            candidates.append(candidate)

        return candidates, global_warnings

    def _score_candidate(
        self,
        candidate: SkillCandidate,
        user_input: str,
        user_tokens: list[str],
        user_language: str,
    ) -> tuple[float, str]:
        """Score a candidate skill against user input.

        Returns: (score, match_reason)
        """
        score = 0.0
        reasons: list[str] = []

        for trigger in candidate.triggers:
            trigger_lower = trigger.lower()
            if trigger_lower in user_input.lower():
                score += self._TRIGGER_WEIGHT
                reasons.append(f"trigger match: '{trigger}'")
                break

        input_lower = user_input.lower()
        for tool in candidate.related_tools:
            if tool.lower() in input_lower:
                score += self._TOOL_WEIGHT
                reasons.append(f"tool reference: '{tool}'")
                break

        desc_tokens = _tokenize(candidate.description)
        desc_sim = _compute_jaccard_similarity(user_tokens, desc_tokens)
        if desc_sim > 0:
            score += desc_sim * self._DESCRIPTION_WEIGHT
            reasons.append(f"description similarity: {desc_sim:.2f}")

        name_tokens = _tokenize(candidate.name)
        name_sim = _compute_jaccard_similarity(user_tokens, name_tokens)
        if name_sim > 0:
            score += name_sim * self._NAME_WEIGHT
            reasons.append(f"name similarity: {name_sim:.2f}")

        return score, ", ".join(reasons) if reasons else "no match"

    def select_skills(
        self,
        user_input: str,
        tool_registry: ToolRegistry | None = None,
    ) -> SkillSelectionRecord:
        """Select relevant skills based on user input.

        Args:
            user_input: The user's message text.
            tool_registry: Optional tool registry for validating related_tools.

        Returns:
            SkillSelectionRecord with selection details.
        """
        record = SkillSelectionRecord(
            user_input=user_input,
            enabled=self._enabled,
            max_skills=self._max_skills,
            status="running",
        )

        if not self._enabled:
            record.status = "disabled"
            record.always_skills = self._loader.get_always_skills()
            self._last_record = record
            return record

        try:
            candidates, global_warnings = self._extract_candidates(tool_registry)
            record.candidates = candidates
            record.warnings = global_warnings

            always_skills = [c for c in candidates if c.is_always]
            record.always_skills = [c.name for c in always_skills]

            regular_candidates = [
                c for c in candidates
                if not c.is_always and c.is_available
            ]

            user_tokens = _tokenize(user_input)
            user_language = _detect_language(user_input)

            scored: list[tuple[SkillCandidate, float, str]] = []
            for candidate in regular_candidates:
                score, reason = self._score_candidate(
                    candidate, user_input, user_tokens, user_language
                )
                candidate.score = score
                candidate.match_reason = reason
                scored.append((candidate, score, reason))

            scored.sort(key=lambda x: x[1], reverse=True)

            top_candidates = scored[: self._max_skills]
            selected_names = [c[0].name for c in top_candidates if c[1] > 0]
            record.selected = selected_names

            skipped: list[SkillSkipped] = []
            for candidate, score, _ in scored[self._max_skills :]:
                if score > 0:
                    skipped.append(SkillSkipped(
                        name=candidate.name,
                        reason="exceeded max_skills limit",
                        score=score,
                    ))
            for candidate, score, _ in scored:
                if score == 0 and candidate.name not in selected_names:
                    skipped.append(SkillSkipped(
                        name=candidate.name,
                        reason="no matching keywords found",
                        score=0.0,
                    ))
            for candidate in candidates:
                if not candidate.is_available and not candidate.is_always:
                    skipped.append(SkillSkipped(
                        name=candidate.name,
                        reason="skill unavailable (unmet requirements)",
                        score=0.0,
                    ))
            record.skipped = skipped

            record.status = "completed"

        except Exception as e:
            record.status = "failed"
            record.warnings.append(f"Orchestrator error: {e}")
            logger.exception("Skill orchestrator failed during selection")

        self._last_record = record
        return record

    def record_tools_used(self, tools_used: list[str]) -> None:
        """Update the last record with tools used in this turn."""
        if self._last_record is not None:
            self._last_record.tools_used = list(tools_used)
