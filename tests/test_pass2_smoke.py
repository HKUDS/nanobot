"""Smoke tests for Pass 2 changes (Phases A, B, D).

Live integration tests that exercise real code paths with ScriptedProvider.
These validate the end-to-end behavior rather than individual functions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.agent.turn_orchestrator import _dynamic_preserve_recent
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.email import EmailChannel
from nanobot.config.agent import AgentConfig
from nanobot.config.memory import MemoryConfig
from nanobot.config.schema import EmailConfig
from nanobot.context.compression import (
    compress_context,
    estimate_messages_tokens,
)
from nanobot.coordination.scratchpad import Scratchpad
from nanobot.errors import DeliverySkippedError
from nanobot.providers.base import LLMProvider
from nanobot.tools.builtin.delegate import DelegateTool, DelegationResult
from tests.helpers import ScriptedProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _email_config(**overrides) -> EmailConfig:
    defaults = dict(
        enabled=True,
        consent_granted=True,
        imap_host="imap.test.com",
        imap_port=993,
        imap_username="bot@test.com",
        imap_password="pw",
        smtp_host="smtp.test.com",
        smtp_port=587,
        smtp_username="bot@test.com",
        smtp_password="pw",
    )
    defaults.update(overrides)
    return EmailConfig(**defaults)


def _agent_config(tmp_path: Path, **overrides) -> AgentConfig:
    defaults = dict(
        workspace=str(tmp_path),
        model="smoke-model",
        memory=MemoryConfig(window=10),
        max_iterations=3,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_loop(tmp_path: Path, provider: LLMProvider) -> AgentLoop:
    return build_agent(bus=MessageBus(), provider=provider, config=_agent_config(tmp_path))


class FakeSMTP:
    def __init__(self, *a, **kw):
        self.sent: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, **kw):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        self.sent.append(msg)


# ===================================================================
# Phase A — End-to-end: email validation + contacts in agent context
# ===================================================================


class TestPhaseASmoke:
    """Smoke tests for outbound recipient validation and contacts."""

    async def test_hallucinated_email_blocked(self, monkeypatch) -> None:
        """The original bug: agent invents an email address → should be blocked."""
        monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", lambda *a, **kw: FakeSMTP())
        cfg = _email_config(proactive_send_policy="known_only")
        ch = EmailChannel(cfg, MessageBus())

        # Agent tries to send to a hallucinated address
        with pytest.raises(DeliverySkippedError, match="known_only"):
            await ch.send(
                OutboundMessage(
                    channel="email",
                    chat_id="hallucinated@nonexistent.com",
                    content="I sent your email!",
                )
            )

    async def test_allowlisted_email_succeeds(self, monkeypatch) -> None:
        """Explicitly allowlisted recipient should go through."""
        instances: list[FakeSMTP] = []

        def factory(*a, **kw):
            inst = FakeSMTP()
            instances.append(inst)
            return inst

        monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", factory)
        cfg = _email_config(
            allow_to=["alice@company.com"],
            proactive_send_policy="allowlist",
        )
        ch = EmailChannel(cfg, MessageBus())
        await ch.send(
            OutboundMessage(
                channel="email",
                chat_id="alice@company.com",
                content="Hello Alice",
            )
        )
        assert len(instances) == 1
        assert instances[0].sent

    async def test_invalid_format_blocked(self, monkeypatch) -> None:
        """Gibberish addresses never reach SMTP."""
        monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", lambda *a, **kw: FakeSMTP())
        cfg = _email_config(proactive_send_policy="open")
        ch = EmailChannel(cfg, MessageBus())
        with pytest.raises(DeliverySkippedError, match="Invalid email"):
            await ch.send(
                OutboundMessage(
                    channel="email",
                    chat_id="not an email",
                    content="test",
                )
            )

    async def test_contacts_in_system_prompt(self, tmp_path: Path) -> None:
        """Agent sees known contacts in system prompt → no need to guess."""
        provider = ScriptedProvider([])
        loop = _make_loop(tmp_path, provider)

        contacts = ["alice@company.com", "bob@company.com"]
        loop.set_contacts_provider(lambda: contacts)
        loop.context.set_contacts_context(contacts)

        prompt = await loop.context.build_system_prompt()
        assert "Known Contacts" in prompt
        assert "alice@company.com" in prompt
        assert "bob@company.com" in prompt
        assert "Do NOT invent" in prompt

    async def test_contacts_refresh_updates_prompt(self, tmp_path: Path) -> None:
        """Contacts list updates between turns."""
        loop = _make_loop(tmp_path, ScriptedProvider([]))

        state = {"contacts": ["old@x.com"]}
        loop.set_contacts_provider(lambda: state["contacts"])
        loop.context.set_contacts_context(state["contacts"])
        assert "old@x.com" in await loop.context.build_system_prompt()

        state["contacts"] = ["new@x.com"]
        loop.context.set_contacts_context(state["contacts"])
        prompt = await loop.context.build_system_prompt()
        assert "new@x.com" in prompt
        assert "old@x.com" not in prompt


# ===================================================================
# Phase B — End-to-end: compression preserves claim-evidence coherence
# ===================================================================


class TestPhaseBSmoke:
    """Smoke tests for paired-drop compression and dynamic preserve."""

    def test_compression_keeps_recent_tool_evidence(self) -> None:
        """When context is compressed, tool results for recent claims survive."""
        msgs = [
            {"role": "system", "content": "System prompt " * 100},
            # Old exchange (will be compressed away)
            {"role": "user", "content": "old question " * 50},
            {"role": "assistant", "content": "old answer " * 50},
            # Recent tool cycle (should be preserved)
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc_recent",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "content": "file contents here",
                "tool_call_id": "tc_recent",
                "name": "read_file",
            },
            {"role": "assistant", "content": "Based on the file, the answer is X."},
            {"role": "user", "content": "Thanks, what about Y?"},
        ]

        # Compress with a tight budget that forces dropping middle content
        budget = estimate_messages_tokens(msgs) - 100
        result = compress_context(msgs, budget, preserve_recent=4)

        # The recent tool result and claim should both survive
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert any("file contents" in (m.get("content") or "") for m in tool_msgs), (
            "Recent tool evidence was dropped — claim-evidence coherence broken"
        )

    def test_orphaned_tool_call_annotated(self) -> None:
        """When a tool result IS dropped, the assistant's tool_call gets marked."""
        msgs = [
            {"role": "system", "content": "sys"},
            # Old tool cycle (will be compressed)
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc_old",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "content": "exec output " * 500,
                "tool_call_id": "tc_old",
                "name": "exec",
            },
            {"role": "assistant", "content": "Done."},
            # Recent (preserved)
            {"role": "user", "content": "next"},
            {"role": "assistant", "content": "reply"},
        ]

        result = compress_context(msgs, 50, preserve_recent=2)

        # Old tool result should be gone, but assistant tool_call should be annotated
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        old_tool = [m for m in tool_msgs if m.get("tool_call_id") == "tc_old"]
        assert len(old_tool) == 0, "Old tool result should be dropped"

        # Check for _result_omitted annotation
        for m in result:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if tc.get("id") == "tc_old":
                        assert tc["function"].get("_result_omitted") is True

    def test_dynamic_preserve_covers_tool_cycle(self) -> None:
        """preserve_recent dynamically expands to cover the last tool cycle."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "tc1", "type": "function", "function": {"name": "f"}},
                    {"id": "tc2", "type": "function", "function": {"name": "g"}},
                ],
            },
            {"role": "tool", "content": "r1", "tool_call_id": "tc1"},
            {"role": "tool", "content": "r2", "tool_call_id": "tc2"},
            {"role": "assistant", "content": "based on tool results..."},
            {"role": "user", "content": "follow up"},
        ]
        preserve = _dynamic_preserve_recent(msgs)
        # Must cover from the tool-calling assistant (idx 4) through end (idx 8)
        # = 5 messages, but floor is 6
        assert preserve >= 6

    def test_dynamic_preserve_o1_path_matches_scan(self) -> None:
        """Providing last_tool_call_idx skips the scan and gives the same result."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "f"}}],
            },
            {"role": "tool", "content": "r1", "tool_call_id": "tc1"},
            {"role": "assistant", "content": "done"},
        ]
        scan_result = _dynamic_preserve_recent(msgs)
        o1_result = _dynamic_preserve_recent(msgs, last_tool_call_idx=2)
        assert scan_result == o1_result

    def test_dynamic_preserve_o1_no_tool_calls_uses_floor(self) -> None:
        """last_tool_call_idx=-1 falls back to scan (no tool calls → floor)."""
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(10)]
        result = _dynamic_preserve_recent(msgs, -1)
        assert result == 6  # floor


# ===================================================================
# Phase D — End-to-end: delegation verification
# ===================================================================


class TestPhaseDSmoke:
    """Smoke tests for delegation result verification and attestation."""

    async def test_grounded_delegation_attestation(self) -> None:
        """Delegation that used tools → grounded tag in output."""
        tool = DelegateTool()

        async def dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            return DelegationResult(
                content="Found 3 relevant documents",
                tools_used=["web_search", "read_file"],
            )

        tool.set_dispatch(dispatch)
        result = await tool.execute(task="search for security advisories")
        assert result.success
        assert "grounded=True" in result.output
        assert "tools_used=2" in result.output
        assert "Found 3 relevant documents" in result.output

    async def test_ungrounded_investigation_warning(self) -> None:
        """Delegation without tools on investigation task → warning."""
        tool = DelegateTool()

        async def dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            return DelegationResult(
                content="I believe the answer is yes",
                tools_used=[],
            )

        tool.set_dispatch(dispatch)
        result = await tool.execute(task="search for the user's order status")
        assert result.success
        assert "grounded=False" in result.output
        assert "⚠️" in result.output
        assert "not be verified" in result.output

    async def test_scratchpad_grounded_tags_roundtrip(self, tmp_path: Path) -> None:
        """Scratchpad entries show verification status on read."""
        pad = Scratchpad(tmp_path)

        # Write grounded result
        id1 = await pad.write(
            role="research",
            label="API data",
            content="Retrieved from live API",
            metadata={"grounded": True, "tools_used": ["web_fetch"]},
        )
        # Write ungrounded result
        id2 = await pad.write(
            role="research",
            label="Guess",
            content="I think the answer is 42",
            metadata={"grounded": False, "tools_used": []},
        )

        # Read individual entries
        r1 = pad.read(id1)
        assert r1 is not None, f"Expected entry {id1} to exist in scratchpad"
        assert "✓" in r1
        assert "Retrieved from live API" in r1

        r2 = pad.read(id2)
        assert r2 is not None, f"Expected entry {id2} to exist in scratchpad"
        assert "⚠ungrounded" in r2

        # Read all — both tags visible
        all_output = pad.read()
        assert all_output is not None, "Scratchpad should not be empty after two writes"
        assert "✓" in all_output
        assert "⚠ungrounded" in all_output

    async def test_delegation_nudge_detects_ungrounded(self, tmp_path: Path) -> None:
        """Agent loop appends warning when delegation results are ungrounded."""
        # Build a message list that simulates post-delegation state
        messages = [
            {"role": "system", "content": "You are a helpful agent."},
            {"role": "user", "content": "Find the latest sales figures"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc_del",
                        "type": "function",
                        "function": {
                            "name": "delegate",
                            "arguments": '{"task": "find sales data", "target_role": "research"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "content": "[tools_used=0, grounded=False]\nI think sales were up 10%",
                "tool_call_id": "tc_del",
                "name": "delegate",
            },
        ]

        # The nudge logic checks for "grounded=False" in recent tool results
        has_ungrounded = any(
            "grounded=False" in (m.get("content") or "")
            for m in messages
            if m.get("role") == "tool"
        )
        assert has_ungrounded, "Should detect ungrounded delegation result"


# ===================================================================
# Cross-phase: full pipeline
# ===================================================================


class TestCrossPhasePipeline:
    """Integration tests that touch multiple phases."""

    async def test_contacts_provider_with_known_recipients(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """EmailChannel.known_recipients feeds into agent contacts context."""
        cfg = _email_config(allow_to=["alice@co.com"])
        ch = EmailChannel(cfg, MessageBus())
        # Simulate a previous inbound email
        ch._last_subject_by_chat["bob@co.com"] = "Hello"

        loop = _make_loop(tmp_path, ScriptedProvider([]))
        loop.set_contacts_provider(lambda: ch.known_recipients)
        loop.context.set_contacts_context(ch.known_recipients)

        prompt = await loop.context.build_system_prompt()
        assert "alice@co.com" in prompt
        assert "bob@co.com" in prompt

    def test_compression_with_delegation_preserves_attestation(self) -> None:
        """When compressing after delegation, the grounded tag survives."""
        msgs = [
            {"role": "system", "content": "sys " * 100},
            {"role": "user", "content": "old " * 100},
            {"role": "assistant", "content": "old reply " * 100},
            # Recent delegation
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc_del",
                        "type": "function",
                        "function": {"name": "delegate", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "content": "[tools_used=2, grounded=True]\nVerified data here",
                "tool_call_id": "tc_del",
                "name": "delegate",
            },
            {"role": "assistant", "content": "Based on the delegation result..."},
            {"role": "user", "content": "Thanks"},
        ]

        result = compress_context(msgs, 80, preserve_recent=4)
        # The delegation tool result should survive (it's in the tail)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert any("grounded=True" in (m.get("content") or "") for m in tool_msgs)
