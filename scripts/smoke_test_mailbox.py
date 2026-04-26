"""Smoke test for the mailbox channel plugin.

Tests the full lifecycle of two agents communicating via filesystem mailbox,
without requiring LLM or API keys.

Usage:
    uv run python scripts/smoke_test_mailbox.py
"""

import asyncio
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from nanobot.bus.events import OutboundMessage
from nanobot.channels.mailbox import MailboxChannel, MailboxManager


class BusMock:
    """Mock bus that captures published InboundMessages."""

    def __init__(self, name: str):
        self.name = name
        self.messages: list = []

    async def publish_inbound(self, msg):
        self.messages.append(msg)


def make_channel(bus: BusMock, root: Path, agent_id: str, **overrides) -> MailboxChannel:
    cfg = {
        "enabled": True,
        "agentId": agent_id,
        "description": f"{agent_id} agent for smoke test",
        "capabilities": ["test"],
        "allowFrom": ["*"],
        "maxConcurrentTasks": 3,
        "pollInterval": 0.05,
        "mailboxesRoot": str(root),
    }
    cfg.update(overrides)
    return MailboxChannel(cfg, bus)


def header(text: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def ok(test_name: str) -> None:
    print(f"  [PASS] {test_name}")


def fail(test_name: str, detail: str = "") -> None:
    print(f"  [FAIL] {test_name}")
    if detail:
        print(f"        {detail}")


async def run_smoke_tests() -> bool:
    tmpdir = tempfile.mkdtemp(prefix="mailbox_smoke_")
    root = Path(tmpdir)
    all_passed = True

    try:
        # ---------------------------------------------------------------
        header("1. Agent Registration")
        # ---------------------------------------------------------------
        bus_a = BusMock("researcher")
        bus_b = BusMock("coder")
        ch_a = make_channel(bus_a, root, "researcher")
        ch_b = make_channel(bus_b, root, "coder")

        await ch_a.start()
        await ch_b.start()

        mgr = MailboxManager(root)
        registry = mgr._read_registry()

        if "researcher" in registry and "coder" in registry:
            ok("Both agents registered in _registry.json")
        else:
            fail("Agent registration", f"Got keys: {list(registry.keys())}")
            all_passed = False

        agents = mgr.list_online_agents()
        ids = {a["agent_id"] for a in agents}
        if ids == {"researcher", "coder"}:
            ok("list_online_agents returns both agents")
        else:
            fail("list_online_agents", f"Got: {ids}")
            all_passed = False

        # ---------------------------------------------------------------
        header("2. Agent A → Agent B messaging")
        # ---------------------------------------------------------------
        outbound = OutboundMessage(
            channel="mailbox",
            chat_id="coder",
            content="Please write a sort function for the project.",
        )
        await ch_a.send(outbound)

        # Verify file in B's inbox
        inbox_files = list((root / "coder" / "inbox").glob("*.msg.json"))
        if len(inbox_files) == 1:
            ok("Message file created in coder's inbox")
        else:
            fail("Message file", f"Expected 1 file, got {len(inbox_files)}")
            all_passed = False

        # Verify message content
        data = json.loads(inbox_files[0].read_text())
        if data["from"] == "researcher" and "sort function" in data["content"]["parts"][0]["text"]:
            ok("Message content correct (from + text)")
        else:
            fail("Message content", f"Got: {data}")
            all_passed = False

        # B polls and receives
        await ch_b._poll_once()
        if len(bus_b.messages) == 1:
            msg = bus_b.messages[0]
            if msg.sender_id == "researcher" and "sort function" in msg.content:
                ok("Agent B received InboundMessage with correct content")
            else:
                fail("InboundMessage content", f"sender={msg.sender_id}, content={msg.content}")
                all_passed = False
        else:
            fail("Agent B receive", f"Expected 1 message, got {len(bus_b.messages)}")
            all_passed = False

        # Verify inbox processed
        if len(list((root / "coder" / "inbox").glob("*.msg.json"))) == 0:
            ok("Inbox cleared after processing")
        else:
            fail("Inbox not cleared")
            all_passed = False

        # ---------------------------------------------------------------
        header("3. Agent B → Agent A response")
        # ---------------------------------------------------------------
        bus_b.messages.clear()

        response = OutboundMessage(
            channel="mailbox",
            chat_id="researcher",
            content="Sort function completed: sort_by_mtime() at utils.py:42",
        )
        await ch_b.send(response)
        await ch_a._poll_once()

        if len(bus_a.messages) == 1:
            msg = bus_a.messages[0]
            if msg.sender_id == "coder" and "sort_by_mtime" in msg.content:
                ok("Agent A received response from coder")
            else:
                fail("Response content", f"sender={msg.sender_id}, content={msg.content}")
                all_passed = False
        else:
            fail("Agent A response", f"Expected 1, got {len(bus_a.messages)}")
            all_passed = False

        # ---------------------------------------------------------------
        header("4. Callback routing (Feishu session)")
        # ---------------------------------------------------------------
        bus_a.messages.clear()
        bus_b.messages.clear()

        # A sends task with callback
        task_msg = OutboundMessage(
            channel="mailbox",
            chat_id="coder",
            content="Analyze the codebase",
            metadata={
                "mailbox_callback": {
                    "channel": "feishu",
                    "chat_id": "user_feishu_123",
                    "session_id": "feishu:user_feishu_123",
                },
            },
        )
        await ch_a.send(task_msg)

        # B receives
        await ch_b._poll_once()
        if len(bus_b.messages) == 1:
            ok("Agent B received task with callback")
        else:
            fail("Task receive")
            all_passed = False

        # B responds with callback forwarded
        bus_b.messages.clear()
        response_with_callback = OutboundMessage(
            channel="mailbox",
            chat_id="researcher",
            content="Analysis complete: 3 modules, 1500 lines",
            metadata={
                "mailbox_callback": {
                    "channel": "feishu",
                    "chat_id": "user_feishu_123",
                    "session_id": "feishu:user_feishu_123",
                },
            },
        )
        await ch_b.send(response_with_callback)
        await ch_a._poll_once()

        if len(bus_a.messages) == 1:
            update = bus_a.messages[0]
            if (update.channel == "feishu"
                    and update.chat_id == "user_feishu_123"
                    and update.session_key_override == "feishu:user_feishu_123"):
                ok("Callback routes to Feishu session correctly")
            else:
                fail("Callback routing", f"channel={update.channel}, chat_id={update.chat_id}")
                all_passed = False
        else:
            fail("Callback receive", f"Expected 1, got {len(bus_a.messages)}")
            all_passed = False

        # ---------------------------------------------------------------
        header("5. Anti-loop: TTL and trace")
        # ---------------------------------------------------------------
        bus_a.messages.clear()

        # Send a message, then check that ttl is decremented and trace populated
        loop_outbound = OutboundMessage(
            channel="mailbox",
            chat_id="coder",
            content="test anti-loop",
            metadata={"mailbox_ttl": 3, "mailbox_trace": []},
        )
        await ch_a.send(loop_outbound)

        inbox_files = list((root / "coder" / "inbox").glob("*.msg.json"))
        latest = sorted(inbox_files)[-1]
        data = json.loads(latest.read_text())
        if data["ttl"] == 2 and "researcher" in data["trace"]:
            ok("TTL decremented (3→2) and trace populated")
        else:
            fail("Anti-loop", f"ttl={data['ttl']}, trace={data['trace']}")
            all_passed = False

        # Test circular route rejection
        circular_outbound = OutboundMessage(
            channel="mailbox",
            chat_id="researcher",
            content="should be rejected",
            metadata={"mailbox_ttl": 3, "mailbox_trace": ["researcher"]},
        )
        before_count = len(list((root / "researcher" / "inbox").glob("*.msg.json")))
        await ch_a.send(circular_outbound)
        after_count = len(list((root / "researcher" / "inbox").glob("*.msg.json")))
        if after_count == before_count:
            ok("Circular route rejected (trace contains target)")
        else:
            fail("Circular route", "Message was written despite circular trace")
            all_passed = False

        # Test TTL=0 rejection
        exhausted_outbound = OutboundMessage(
            channel="mailbox",
            chat_id="coder",
            content="should be rejected",
            metadata={"mailbox_ttl": 0, "mailbox_trace": []},
        )
        before_count = len(list((root / "coder" / "inbox").glob("*.msg.json")))
        await ch_a.send(exhausted_outbound)
        after_count = len(list((root / "coder" / "inbox").glob("*.msg.json")))
        if after_count == before_count:
            ok("TTL=0 rejected (exhausted hop count)")
        else:
            fail("TTL=0", "Message was written despite TTL=0")
            all_passed = False

        # ---------------------------------------------------------------
        header("6. allowFrom access control")
        # ---------------------------------------------------------------
        bus_c = BusMock("restricted")
        ch_c = make_channel(bus_c, root, "restricted", allowFrom=["researcher"])
        await ch_c.start()

        # Stranger sends message — should be blocked
        mgr.send("stranger", "restricted", {
            "type": "message",
            "content": {"parts": [{"type": "text", "text": "should be blocked"}]},
        })
        await ch_c._poll_once()

        if len(bus_c.messages) == 0:
            ok("Stranger blocked by allowFrom=['researcher']")
        else:
            fail("allowFrom", f"Got {len(bus_c.messages)} messages, expected 0")
            all_passed = False

        # Researcher sends message — should pass
        bus_c.messages.clear()
        mgr.send("researcher", "restricted", {
            "type": "message",
            "content": {"parts": [{"type": "text", "text": "should pass"}]},
        })
        await ch_c._poll_once()

        if len(bus_c.messages) == 1:
            ok("Researcher allowed by allowFrom=['researcher']")
        else:
            fail("allowFrom allow", f"Got {len(bus_c.messages)} messages, expected 1")
            all_passed = False

        await ch_c.stop()

        # ---------------------------------------------------------------
        header("7. Heartbeat and status")
        # ---------------------------------------------------------------
        before_hb = mgr._read_registry()["researcher"]["last_heartbeat"]
        time.sleep(0.02)
        mgr.heartbeat("researcher")
        after_hb = mgr._read_registry()["researcher"]["last_heartbeat"]
        if after_hb > before_hb:
            ok("Heartbeat updates timestamp")
        else:
            fail("Heartbeat")
            all_passed = False

        # ---------------------------------------------------------------
        header("8. Stop and offline")
        # ---------------------------------------------------------------
        await ch_a.stop()
        await ch_b.stop()

        registry = mgr._read_registry()
        if registry["researcher"]["status"] == "offline" and registry["coder"]["status"] == "offline":
            ok("Both agents marked offline after stop()")
        else:
            fail("Offline status", f"researcher={registry['researcher']['status']}, coder={registry['coder']['status']}")
            all_passed = False

        online = mgr.list_online_agents()
        agent_ids = {a["agent_id"] for a in online}
        if "researcher" not in agent_ids and "coder" not in agent_ids:
            ok("Offline agents excluded from list_online_agents()")
        else:
            fail("Online list", f"Still shows: {agent_ids}")
            all_passed = False

        # ---------------------------------------------------------------
        # Summary
        # ---------------------------------------------------------------
        print(f"\n{'='*60}")
        if all_passed:
            print("  ALL SMOKE TESTS PASSED")
        else:
            print("  SOME TESTS FAILED — see above for details")
        print(f"{'='*60}\n")

        return all_passed

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    passed = asyncio.run(run_smoke_tests())
    sys.exit(0 if passed else 1)
