"""Memory consolidation evaluation framework.

Measures the quality of memory consolidation by feeding known conversations
through the consolidation pipeline and checking whether key facts survive.

Metrics:
    - Retention rate: % of key facts preserved after consolidation
    - Compression ratio: tokens before / tokens after
    - Consolidation success: whether consolidation completed without fallback
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


@dataclass
class ConsolidationScenario:
    """A test scenario for evaluating memory consolidation quality."""

    name: str
    description: str
    messages: list[dict[str, Any]]
    key_facts: list[str]
    scripted_response: LLMResponse


@dataclass
class ConsolidationResult:
    """Result of evaluating a consolidation scenario."""

    scenario_name: str
    success: bool
    retained_facts: list[str]
    missed_facts: list[str]
    retention_rate: float
    input_chars: int
    output_chars: int
    compression_ratio: float


class ScriptedProvider(LLMProvider):
    """Deterministic provider for CI-safe evaluation."""

    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        return "eval-model"


async def evaluate_scenario(
    scenario: ConsolidationScenario,
    workspace_path,
) -> ConsolidationResult:
    """Run a single consolidation scenario and measure quality."""
    store = MemoryStore(workspace_path)
    provider = ScriptedProvider([scenario.scripted_response])

    input_chars = sum(len(m.get("content", "")) for m in scenario.messages)

    success = await store.consolidate(scenario.messages, provider, "eval-model")

    memory_content = store.read_long_term()
    history_content = ""
    if store.history_file.exists():
        history_content = store.history_file.read_text(encoding="utf-8")

    combined_output = f"{memory_content}\n{history_content}".lower()
    output_chars = len(memory_content) + len(history_content)

    retained = []
    missed = []
    for fact in scenario.key_facts:
        if fact.lower() in combined_output:
            retained.append(fact)
        else:
            missed.append(fact)

    retention_rate = len(retained) / len(scenario.key_facts) if scenario.key_facts else 1.0
    compression_ratio = input_chars / max(1, output_chars)

    return ConsolidationResult(
        scenario_name=scenario.name,
        success=success,
        retained_facts=retained,
        missed_facts=missed,
        retention_rate=retention_rate,
        input_chars=input_chars,
        output_chars=output_chars,
        compression_ratio=compression_ratio,
    )


def make_save_memory_response(history_entry: str, memory_update: str) -> LLMResponse:
    """Helper to create a scripted save_memory tool-call response."""
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(
                id="eval_call_1",
                name="save_memory",
                arguments={
                    "history_entry": history_entry,
                    "memory_update": memory_update,
                },
            )
        ],
    )


# --- Built-in Scenarios ---


def scenario_multi_turn_tools() -> ConsolidationScenario:
    """Multi-turn conversation with tool usage."""
    messages = [
        {
            "role": "user",
            "content": "Search for Python async best practices",
            "timestamp": "2026-03-19 10:00",
        },
        {
            "role": "assistant",
            "content": "I'll search for that.",
            "timestamp": "2026-03-19 10:01",
            "tools_used": ["web_search"],
        },
        {
            "role": "user",
            "content": "Now save a summary to ~/notes/async.md",
            "timestamp": "2026-03-19 10:02",
        },
        {
            "role": "assistant",
            "content": "I've saved the async best practices summary to ~/notes/async.md",
            "timestamp": "2026-03-19 10:03",
            "tools_used": ["write_file"],
        },
        {
            "role": "user",
            "content": "What's the weather in Hong Kong?",
            "timestamp": "2026-03-19 10:04",
        },
        {
            "role": "assistant",
            "content": "It's 28°C and sunny in Hong Kong.",
            "timestamp": "2026-03-19 10:05",
            "tools_used": ["web_search"],
        },
    ]
    return ConsolidationScenario(
        name="multi_turn_tools",
        description="Multi-turn conversation with web search and file write tools",
        messages=messages,
        key_facts=["Python", "async", "async.md", "Hong Kong"],
        scripted_response=make_save_memory_response(
            history_entry="[2026-03-19 10:00] User searched for Python async best practices, "
            "saved summary to ~/notes/async.md. Also checked weather in Hong Kong (28°C, sunny).",
            memory_update="# Memory\n- User interested in Python async patterns\n"
            "- Saved async best practices to ~/notes/async.md\n"
            "- User asked about Hong Kong weather",
        ),
    )


def scenario_scattered_facts() -> ConsolidationScenario:
    """Important facts scattered across a long conversation."""
    messages = [
        {
            "role": "user",
            "content": "My name is Alex and I work at TechCorp",
            "timestamp": "2026-03-19 09:00",
        },
        {
            "role": "assistant",
            "content": "Nice to meet you, Alex!",
            "timestamp": "2026-03-19 09:01",
        },
        {
            "role": "user",
            "content": "Can you help me with a Python script?",
            "timestamp": "2026-03-19 09:02",
        },
        {
            "role": "assistant",
            "content": "Of course! What do you need?",
            "timestamp": "2026-03-19 09:03",
        },
        {
            "role": "user",
            "content": "I need to parse CSV files for our Q1 report",
            "timestamp": "2026-03-19 09:04",
        },
        {
            "role": "assistant",
            "content": "I can help with that. Let me write a script.",
            "timestamp": "2026-03-19 09:05",
        },
        {
            "role": "user",
            "content": "Oh by the way, my email is alex@techcorp.com",
            "timestamp": "2026-03-19 09:06",
        },
        {
            "role": "assistant",
            "content": "Got it. Here's the CSV parsing script...",
            "timestamp": "2026-03-19 09:07",
        },
        {
            "role": "user",
            "content": "We use PostgreSQL for our database",
            "timestamp": "2026-03-19 09:08",
        },
        {
            "role": "assistant",
            "content": "Good to know. I can add database export too.",
            "timestamp": "2026-03-19 09:09",
        },
        {
            "role": "user",
            "content": "The deadline for the report is March 25th",
            "timestamp": "2026-03-19 09:10",
        },
        {
            "role": "assistant",
            "content": "I'll keep that in mind.",
            "timestamp": "2026-03-19 09:11",
        },
    ]
    return ConsolidationScenario(
        name="scattered_facts",
        description="Key user facts scattered across casual conversation",
        messages=messages,
        key_facts=["Alex", "TechCorp", "CSV", "Q1 report", "PostgreSQL", "March 25"],
        scripted_response=make_save_memory_response(
            history_entry="[2026-03-19 09:00] User Alex from TechCorp requested help with a Python "
            "CSV parsing script for Q1 report. Uses PostgreSQL. Deadline March 25th. "
            "Email: alex@techcorp.com.",
            memory_update="# Memory\n- User: Alex, works at TechCorp\n"
            "- Email: alex@techcorp.com\n"
            "- Database: PostgreSQL\n"
            "- Current project: Q1 report (deadline March 25th)\n"
            "- Needed: CSV parsing script for Q1 report",
        ),
    )


def scenario_buried_important_info() -> ConsolidationScenario:
    """Critical info buried in noise — tests whether consolidation preserves it."""
    messages = [
        {"role": "user", "content": "What's the weather today?", "timestamp": "2026-03-19 08:00"},
        {"role": "assistant", "content": "It's 22°C and cloudy.", "timestamp": "2026-03-19 08:01"},
        {"role": "user", "content": "Tell me a joke", "timestamp": "2026-03-19 08:02"},
        {
            "role": "assistant",
            "content": "Why do programmers prefer dark mode?",
            "timestamp": "2026-03-19 08:03",
        },
        {
            "role": "user",
            "content": "IMPORTANT: Never run rm -rf on production server zeus-prod-01",
            "timestamp": "2026-03-19 08:04",
        },
        {
            "role": "assistant",
            "content": "Understood. I will never run destructive commands on zeus-prod-01.",
            "timestamp": "2026-03-19 08:05",
        },
        {"role": "user", "content": "What's 2+2?", "timestamp": "2026-03-19 08:06"},
        {"role": "assistant", "content": "4.", "timestamp": "2026-03-19 08:07"},
        {"role": "user", "content": "Can you summarize the news?", "timestamp": "2026-03-19 08:08"},
        {
            "role": "assistant",
            "content": "Here are today's headlines...",
            "timestamp": "2026-03-19 08:09",
        },
    ]
    return ConsolidationScenario(
        name="buried_important_info",
        description="Critical safety instruction buried among trivial messages",
        messages=messages,
        key_facts=["zeus-prod-01", "rm -rf", "never run"],
        scripted_response=make_save_memory_response(
            history_entry="[2026-03-19 08:00] Casual chat (weather, jokes, math). "
            "CRITICAL: User instructed never to run rm -rf on production server zeus-prod-01.",
            memory_update="# Memory\n## Safety Rules\n- NEVER run rm -rf on production server zeus-prod-01\n"
            "\n## General\n- User enjoys casual conversation",
        ),
    )


def scenario_consolidation_failure() -> ConsolidationScenario:
    """Simulates consolidation failure (no tool call returned)."""
    messages = [
        {
            "role": "user",
            "content": "Remember that I prefer dark mode",
            "timestamp": "2026-03-19 12:00",
        },
        {"role": "assistant", "content": "Noted!", "timestamp": "2026-03-19 12:01"},
    ]
    return ConsolidationScenario(
        name="consolidation_failure",
        description="LLM fails to call save_memory tool — tests degraded behavior",
        messages=messages,
        key_facts=["dark mode"],
        scripted_response=LLMResponse(
            content="I summarized the conversation.",
            tool_calls=[],
            finish_reason="stop",
        ),
    )


def scenario_empty_conversation() -> ConsolidationScenario:
    """Edge case: empty conversation should succeed trivially."""
    return ConsolidationScenario(
        name="empty_conversation",
        description="Empty message list — should return True without calling LLM",
        messages=[],
        key_facts=[],
        scripted_response=LLMResponse(content="", tool_calls=[]),
    )


ALL_SCENARIOS = [
    scenario_multi_turn_tools,
    scenario_scattered_facts,
    scenario_buried_important_info,
    scenario_consolidation_failure,
    scenario_empty_conversation,
]
