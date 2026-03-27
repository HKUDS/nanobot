"""Unit tests for evidence extraction in AnswerVerifier."""

from __future__ import annotations

from nanobot.agent.verifier import AnswerVerifier
from tests.helpers import ScriptedProvider


def _make_verifier() -> AnswerVerifier:
    return AnswerVerifier(
        provider=ScriptedProvider([]),
        model="test-model",
        temperature=0.7,
        max_tokens=4096,
        verification_mode="always",
        memory_uncertainty_threshold=0.5,
    )


class TestExtractEvidenceToolResults:
    def test_single_tool_result(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is the vault path?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "obsidian vault path"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "exec",
                "content": "<tool_result>\nname\tProject Management\npath\tC:\\Users\\user\\Documents\n</tool_result>",
            },
            {"role": "assistant", "content": "Your vault is at C:\\Users\\user\\Documents"},
        ]
        evidence = v._extract_evidence(messages)
        assert "[tool:exec]" in evidence
        assert "obsidian vault path" in evidence
        assert "Project Management" in evidence

    def test_no_tool_results_returns_empty(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        evidence = v._extract_evidence(messages)
        assert evidence == ""

    def test_multiple_tool_results(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "No memory."},
            {"role": "user", "content": "Search for DS10540"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "load_skill",
                            "arguments": '{"name": "obsidian-cli"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "load_skill",
                "content": "<tool_result>\nSkill loaded.\n</tool_result>",
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "obsidian search query=DS10540"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_2",
                "name": "exec",
                "content": "<tool_result>\n(no output)\n</tool_result>",
            },
            {"role": "assistant", "content": "No results found."},
        ]
        evidence = v._extract_evidence(messages)
        assert "[tool:load_skill]" in evidence
        assert "[tool:exec]" in evidence
        assert "obsidian search query=DS10540" in evidence
