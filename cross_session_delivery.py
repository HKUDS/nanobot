"""Patch: Prevent cross-session response delivery in agent loop.

Bug: When a user sends a message in Session A, then quickly switches to
Session B and sends another message, the response for Session A can appear
in Session B. This happens because the agent loop's delivery route may be
overwritten by concurrent session processing.

Fix: Capture the originating session_key at message receipt time and verify
it matches at delivery time. If they don't match, route the response to
the originating session instead of the currently focused one.

Applied to: /Users/user/.nanobot/venv/lib/python3.14/site-packages/nanobot/agent/loop.py
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

LOOP_PY = Path("/Users/user/.nanobot/venv/lib/python3.14/site-packages/nanobot/agent/loop.py")

PATCHED_MARKER = "# [patched: cross-session-delivery-fix]"


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def apply_patch() -> bool:
    """Apply the cross-session delivery fix to loop.py."""
    original = LOOP_PY.read_text()

    if PATCHED_MARKER in original:
        print(f"Already patched (marker found). hash={_hash(original)}")
        return False

    # The fix: in _dispatch, ensure delivery.route always uses the ORIGINAL
    # msg.chat_id, and capture session_key as a local variable that cannot
    # be overwritten by concurrent processing.

    # Find the delivery creation line and ensure route.chat_id is locked
    old_dispatch = '''        delivery = self.turn_delivery_factory.unrouted(msg, session_key)
        pending: asyncio.Queue | None = None
        try:
            async with lock, gate:'''

    new_dispatch = f'''        # {PATCHED_MARKER}
        # Lock the originating chat_id so delivery never routes to wrong session
        _originating_chat_id: str = msg.chat_id
        _originating_session_key: str = session_key
        delivery = self.turn_delivery_factory.unrouted(msg, session_key)
        pending: asyncio.Queue | None = None
        try:
            async with lock, gate:'''

    if old_dispatch not in original:
        print(f"ERROR: target code not found in loop.py")
        return False

    patched = original.replace(old_dispatch, new_dispatch, 1)

    # Also ensure delivery.complete uses the originating chat_id
    old_complete = '''                    await delivery.complete(
                        response,
                        publish_completion=not continuing,
                    )'''

    new_complete = f'''                    # {PATCHED_MARKER}: ensure response routes to originating session
                    if delivery.route.chat_id != _originating_chat_id:
                        from nanobot.agent.turn_delivery import TurnRoute
                        delivery.route = TurnRoute(
                            channel=delivery.route.channel,
                            chat_id=_originating_chat_id,
                            metadata=dict(delivery.route.metadata),
                            publish_lifecycle=delivery.route.publish_lifecycle,
                        )
                    await delivery.complete(
                        response,
                        publish_completion=not continuing,
                    )'''

    if old_complete not in patched:
        print(f"ERROR: delivery.complete target not found")
        return False

    patched = patched.replace(old_complete, new_complete, 1)

    LOOP_PY.write_text(patched)
    print(f"Patched successfully. hash={_hash(patched)}")
    return True


def verify_patch() -> bool:
    """Verify the patch is applied."""
    content = LOOP_PY.read_text()
    return PATCHED_MARKER in content


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        ok = verify_patch()
        print(f"Patch status: {'APPLIED' if ok else 'NOT APPLIED'}")
    else:
        ok = apply_patch()
        print(f"Result: {'SUCCESS' if ok else 'SKIPPED/FAILED'}")
