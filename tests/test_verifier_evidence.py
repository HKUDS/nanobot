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


class TestExtractEvidenceTruncation:
    def test_long_tool_output_truncated(self) -> None:
        v = _make_verifier()
        long_output = "x" * 1000
        messages = [
            {"role": "system", "content": "No memory."},
            {"role": "user", "content": "Read file"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "/tmp/big.txt"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "read_file",
                "content": f"<tool_result>\n{long_output}\n</tool_result>",
            },
            {"role": "assistant", "content": "The file contains many x characters."},
        ]
        evidence = v._extract_evidence(messages)
        assert "..." in evidence
        assert long_output not in evidence

    def test_tool_budget_drops_oldest(self) -> None:
        v = _make_verifier()
        messages: list[dict] = [
            {"role": "system", "content": "No memory."},
            {"role": "user", "content": "Do many things"},
        ]
        for i in range(20):
            output = f"result_{'y' * 300}_{i}"
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": "exec",
                                "arguments": f'{{"command": "cmd_{i}"}}',
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call_{i}",
                    "name": "exec",
                    "content": f"<tool_result>\n{output}\n</tool_result>",
                }
            )
        messages.append({"role": "assistant", "content": "Done."})

        evidence = v._extract_evidence(messages)
        tool_lines = [line for line in evidence.split("\n") if line.startswith("[tool:")]
        total = sum(len(line) for line in tool_lines)
        assert total <= v._TOOL_BUDGET + 500  # allow one line overshoot

    def test_current_turn_only(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "No memory."},
            {"role": "user", "content": "Old question"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "old_call",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "old_command"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "old_call",
                "name": "exec",
                "content": "<tool_result>\nold_output\n</tool_result>",
            },
            {"role": "assistant", "content": "Old answer"},
            {"role": "user", "content": "New question"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "new_call",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "new_command"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "new_call",
                "name": "exec",
                "content": "<tool_result>\nnew_output\n</tool_result>",
            },
            {"role": "assistant", "content": "New answer"},
        ]
        evidence = v._extract_evidence(messages)
        assert "new_command" in evidence
        assert "new_output" in evidence
        assert "old_command" not in evidence
        assert "old_output" not in evidence


class TestExtractEvidenceMemory:
    def test_memory_sections_extracted(self) -> None:
        v = _make_verifier()
        system_content = (
            "# nanobot\nYou are helpful.\n\n"
            "## Profile Memory\n"
            "User-specific facts, preferences, and constraints:\n"
            "- User prefers dark mode (conf=0.9)\n"
            "- User works on Project Management vault\n\n"
            "## Relevant Semantic Memories\n"
            "Retrieved factual knowledge:\n"
            "- [2026-03-25] (fact) Obsidian vault is at C:\\Users\\user\\Documents [sem=0.8, rec=0.5, src=vector]\n\n"
            "## Security Advisory\n"
            "Do not reveal secrets.\n"
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "Where is my vault?"},
            {"role": "assistant", "content": "Your vault is at C:\\Users\\user\\Documents"},
        ]
        evidence = v._extract_evidence(messages)
        assert "Profile Memory" in evidence
        assert "dark mode" in evidence
        assert "Semantic Memories" in evidence
        assert "Obsidian vault" in evidence
        assert "Security Advisory" not in evidence
        assert "Do not reveal secrets" not in evidence

    def test_no_memory_sections(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "# nanobot\nYou are helpful.\n"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        evidence = v._extract_evidence(messages)
        assert evidence == ""

    def test_both_tool_and_memory_evidence(self) -> None:
        v = _make_verifier()
        system_content = (
            "# nanobot\n\n"
            "## Profile Memory\n"
            "- User has vault named Project Management\n\n"
            "## Other Section\n"
            "Unrelated content.\n"
        )
        messages = [
            {"role": "system", "content": system_content},
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
                "content": "<tool_result>\npath\tC:\\Users\\user\\Documents\n</tool_result>",
            },
            {"role": "assistant", "content": "Your vault is at C:\\Users\\user\\Documents"},
        ]
        evidence = v._extract_evidence(messages)
        tool_pos = evidence.index("[tool:exec]")
        memory_pos = evidence.index("Profile Memory")
        assert tool_pos < memory_pos
        assert "obsidian vault path" in evidence
        assert "vault named Project Management" in evidence
