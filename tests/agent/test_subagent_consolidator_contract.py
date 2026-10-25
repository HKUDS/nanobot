"""Public construction and execution contracts for subagent consolidation."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from nanobot.agent.memory import Consolidator, MemoryStore
from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager
from nanobot.utils.helpers import estimate_prompt_tokens_chain
from nanobot.utils.llm_runtime import LLMRuntime


def test_subagent_requires_consolidator_at_construction(tmp_path):
    with pytest.raises(TypeError, match="consolidator"):
        SubagentManager(workspace=tmp_path, bus=MessageBus(), max_tool_result_chars=16_000)


def test_subagent_rejects_explicit_none_consolidator(tmp_path):
    with pytest.raises(TypeError, match="consolidator"):
        SubagentManager(
            workspace=tmp_path,
            bus=MessageBus(),
            max_tool_result_chars=16_000,
            consolidator=None,
        )


class _EvidenceProvider(LLMProvider):
    """Model protocol fixture; all execution and consolidation machinery is real."""

    def __init__(self):
        super().__init__(provider_name="test")
        self.generation = GenerationSettings(max_tokens=2048)
        self.reads = 0
        self.summaries = 0

    def get_default_model(self):
        return "test"

    def estimate_prompt_tokens(self, messages, tools, model):
        # Deterministic provider counter; no tokenizer cache or network dependency.
        return len(json.dumps([messages, tools])) // 2, "test-provider"

    async def chat(self, messages, tools=None, **kwargs):
        text = json.dumps(messages)
        tokens, _ = estimate_prompt_tokens_chain(self, "test", messages, tools)
        assert tokens <= 21_952
        if self.reads:
            assert "EARLY_EVIDENCE_78291" in text
        if messages[-1].get("content", "").startswith("Create a compact replacement checkpoint"):
            self.summaries += 1
            return LLMResponse(content="- [ephemeral] Preserve EARLY_EVIDENCE_78291.")
        if self.reads == 8:
            return LLMResponse(content="Completed: EARLY_EVIDENCE_78291")
        index = self.reads
        self.reads += 1
        return LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id=f"read-{index}",
            name="read_file",
            arguments={"path": f"evidence-{index}.txt"},
        )])


def _files(root: Path):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("background", [False, True])
async def test_sdk_preserves_evidence_across_transient_compaction(tmp_path, background):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for index in range(8):
        lines = ["EARLY_EVIDENCE_78291" if index == 0 else f"EVIDENCE_{index}"]
        lines += [
            f"{n:04d} " + hashlib.sha256(f"{index}/{n}".encode()).hexdigest()[:32]
            for n in range(330)
        ]
        (workspace / f"evidence-{index}.txt").write_text("\n".join(lines), encoding="utf-8")
    sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    consolidator = Consolidator(
        MemoryStore(workspace), sessions, lambda **kwargs: [], lambda: [],
    )
    bus = MessageBus()
    provider = _EvidenceProvider()
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=24_000)
    manager = SubagentManager(
        workspace=workspace,
        bus=bus,
        max_tool_result_chars=16_000,
        max_iterations=12,
        restrict_to_workspace=True,
        consolidator=consolidator,
    )
    before = _files(tmp_path)
    try:
        kwargs = {
            "task": "Read evidence-0.txt through evidence-7.txt and retain the early identifier.",
            "session_key": "test:parent",
            "runtime": runtime,
        }
        if background:
            await manager.spawn(**kwargs)
            event = await asyncio.wait_for(bus.consume_inbound(), timeout=15)
            assert event.session_key_override == "test:parent"
            assert event.metadata["injected_event"] == "subagent_result"
            result = event.content
        else:
            result = await asyncio.wait_for(manager.run_inline(**kwargs), timeout=15)
        assert "Completed: EARLY_EVIDENCE_78291" in result
        assert provider.reads == 8
        assert provider.summaries >= 2
        assert _files(tmp_path) == before
    finally:
        await manager.close()
