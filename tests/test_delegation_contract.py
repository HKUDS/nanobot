"""Tests for nanobot.agent.delegation_contract module."""

from __future__ import annotations

from nanobot.agent.delegation_contract import (
    _SCRATCHPAD_INJECTION_LIMIT,
    _cap_scratchpad_for_injection,
    extract_user_request,
    gather_recent_tool_results,
)


def test_cap_scratchpad_under_limit() -> None:
    short = "hello world"
    assert _cap_scratchpad_for_injection(short) == short


def test_cap_scratchpad_over_limit() -> None:
    content = "x" * (_SCRATCHPAD_INJECTION_LIMIT + 500)
    result = _cap_scratchpad_for_injection(content)
    assert len(result) < len(content)
    assert result.startswith("x" * _SCRATCHPAD_INJECTION_LIMIT)
    assert "[truncated" in result


def test_extract_user_request_empty() -> None:
    assert extract_user_request([]) == ""


def test_extract_user_request_found() -> None:
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Tell me about Python"},
        {"role": "assistant", "content": "Sure!"},
    ]
    assert extract_user_request(messages) == "Tell me about Python"


def test_gather_recent_tool_results_empty() -> None:
    assert gather_recent_tool_results([]) == ""
