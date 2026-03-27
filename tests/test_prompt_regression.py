"""Regression tests for prompt template assets.

These tests ensure that:
1. All expected prompt template files exist.
2. Each prompt is non-empty and loadable via PromptLoader.
3. Key phrases required for correct agent behavior are present.
4. Prompt manifest is in sync with actual files.

If a test fails, it means a prompt was accidentally deleted, corrupted,
or modified in a way that removes essential functionality.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.context.prompt_loader import PromptLoader

# ---------------------------------------------------------------------------
# Expected prompts and their required key phrases
# ---------------------------------------------------------------------------

# Each prompt must exist and contain at least one of the listed phrases
EXPECTED_PROMPTS: dict[str, list[str]] = {
    "compress": ["summar"],
    "consolidation": ["consolidat", "memory", "save_memory"],
    "critique": ["crit", "review", "evaluat"],
    "deck_synthesis": ["synthesiz", "deck", "slide"],
    "delegation_agent": ["specialist", "tool"],
    "delegation_schema": ["Findings", "Evidence", "Confidence"],
    "extractor": ["extractor", "save_events"],
    "failure_strategy": ["fail", "alternative"],
    "heartbeat": ["heartbeat", "tool"],
    "identity": ["You are", "agent"],
    "memory_header": ["memory", "knowledge"],
    "micro_extract": ["memory", "extract", "remember"],
    "nudge_final_answer": ["answer", "final"],
    "nudge_malformed_fallback": ["malform", "fallback"],
    "plan": ["plan", "step"],
    "progress": ["progress", "status"],
    "reasoning": ["tool", "fallback", "target type"],
    "recovery": ["previous attempt", "answer", "tool"],
    "reflect": ["reflect", "what went wrong", "analyz"],
    "revision_request": ["issue", "revis", "concern"],
    "security_advisory": ["secur", "sensiti"],
    "self_check": ["claim", "not found", "verified"],
    "tool_guide": ["intent", "list_dir", "anti-pattern"],
    "skills_header": ["skill"],
    "slide_analysis": ["slide", "analyz"],
    "summary_system": ["summar", "tool"],
    "unavailable_tools": ["unavailabl", "tool"],
    "verification_required": ["verif"],
}

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "nanobot" / "templates" / "prompts"


# ---------------------------------------------------------------------------
# All prompt files exist
# ---------------------------------------------------------------------------


class TestPromptFilesExist:
    """Every expected prompt template file must exist on disk."""

    @pytest.mark.parametrize("name", list(EXPECTED_PROMPTS.keys()))
    def test_prompt_file_exists(self, name: str):
        path = PROMPTS_DIR / f"{name}.md"
        assert path.exists(), f"Prompt template '{name}.md' is missing from {PROMPTS_DIR}"
        assert path.stat().st_size > 0, f"Prompt template '{name}.md' is empty"


# ---------------------------------------------------------------------------
# PromptLoader can load all prompts
# ---------------------------------------------------------------------------


class TestPromptLoaderLoadsAll:
    """PromptLoader.get() must return non-empty text for every expected prompt."""

    def test_all_prompts_loadable(self):
        loader = PromptLoader()
        for name in EXPECTED_PROMPTS:
            text = loader.get(name)
            assert isinstance(text, str), f"Prompt '{name}' did not return a string"
            assert len(text.strip()) > 0, f"Prompt '{name}' loaded as empty"


# ---------------------------------------------------------------------------
# Key phrases are present
# ---------------------------------------------------------------------------


class TestPromptKeyPhrases:
    """Each prompt must contain phrases essential for its function."""

    @pytest.mark.parametrize(
        "name,phrases",
        list(EXPECTED_PROMPTS.items()),
        ids=list(EXPECTED_PROMPTS.keys()),
    )
    def test_required_phrases_present(self, name: str, phrases: list[str]):
        loader = PromptLoader()
        text = loader.get(name).lower()
        matches = [p for p in phrases if p.lower() in text]
        assert len(matches) > 0, (
            f"Prompt '{name}' must contain at least one of {phrases}, "
            f"but none were found in: {text[:200]}..."
        )


# ---------------------------------------------------------------------------
# No unexpected prompt files (detect orphans)
# ---------------------------------------------------------------------------


class TestNoOrphanPrompts:
    """All .md files in the prompts directory should be in the expected set."""

    def test_no_untracked_prompts(self):
        if not PROMPTS_DIR.is_dir():
            pytest.skip("Prompts directory not found")
        actual = {p.stem for p in PROMPTS_DIR.glob("*.md")}
        expected = set(EXPECTED_PROMPTS.keys())
        orphans = actual - expected
        # Orphans are not necessarily wrong, but should be tracked
        if orphans:
            pytest.fail(
                f"Untracked prompt files found: {orphans}. "
                "Add them to EXPECTED_PROMPTS in test_prompt_regression.py "
                "or remove them if unused."
            )
