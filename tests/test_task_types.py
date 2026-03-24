"""Tests for nanobot.coordination.task_types module."""

from __future__ import annotations

from nanobot.coordination.task_types import TASK_TYPES, classify_task_type, has_parallel_structure


def test_task_types_has_seven_keys() -> None:
    assert len(TASK_TYPES) == 7


def test_classify_code_analysis() -> None:
    result = classify_task_type("code", "analyze the authentication module")
    assert result == "local_code_analysis"


def test_classify_web_research() -> None:
    result = classify_task_type("research", "what are the current industry trends in AI")
    assert result == "web_research"


def test_classify_general_fallback() -> None:
    result = classify_task_type("general", "hello")
    assert result == "general"


def test_has_parallel_structure_numbered() -> None:
    assert has_parallel_structure("1. First task 2. Second task 3. Third task") is True


def test_has_parallel_structure_plain_text() -> None:
    assert has_parallel_structure("just do this one thing") is False
