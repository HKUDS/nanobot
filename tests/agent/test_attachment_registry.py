"""Unit tests for the turn-scoped attachment registry (#4345)."""

from __future__ import annotations

import asyncio
import contextvars

from nanobot.agent import attachment_registry


def test_mint_then_resolve_roundtrips() -> None:
    attachment_registry.begin_turn()
    handle = attachment_registry.mint("/srv/uploads/a.png")
    assert handle == "attachment_1"
    assert attachment_registry.resolve(handle) == "/srv/uploads/a.png"


def test_sequential_ids_within_a_turn() -> None:
    attachment_registry.begin_turn()
    h1 = attachment_registry.mint("/a.png")
    h2 = attachment_registry.mint("/b.png")
    assert [h1, h2] == ["attachment_1", "attachment_2"]
    assert attachment_registry.resolve(h2) == "/b.png"


def test_unknown_and_forged_ids_resolve_to_none() -> None:
    attachment_registry.begin_turn()
    attachment_registry.mint("/a.png")
    assert attachment_registry.resolve("attachment_99") is None
    assert attachment_registry.resolve("/etc/passwd") is None  # a path is not a key
    assert attachment_registry.resolve("") is None


def test_begin_turn_resets_with_a_fresh_dict() -> None:
    attachment_registry.begin_turn()
    first = attachment_registry.mint("/old.png")
    assert attachment_registry.resolve(first) == "/old.png"

    attachment_registry.begin_turn()
    # The id numbering restarts and the previous turn's mapping is gone.
    assert attachment_registry.resolve(first) is None
    second = attachment_registry.mint("/new.png")
    assert second == "attachment_1"
    assert attachment_registry.resolve(second) == "/new.png"


def test_child_context_mint_does_not_leak_into_parent() -> None:
    """A mint in a child context must not bleed back into the parent. Guards against
    ``ContextVar(default={})``, whose single shared mutable dict would leak the child's
    entry into every other context."""
    # Establish a known-empty parent turn first.
    attachment_registry.begin_turn()

    def _mint_in_child() -> None:
        attachment_registry.begin_turn()
        attachment_registry.mint("/child.png")

    contextvars.copy_context().run(_mint_in_child)

    # The child's mint did not appear in the parent's (still-empty) registry.
    assert attachment_registry.resolve("attachment_1") is None


def test_registry_isolated_across_concurrent_turns() -> None:
    """Two turns running in their own contexts each see only their own mints."""

    async def _turn(path: str) -> str | None:
        attachment_registry.begin_turn()
        handle = attachment_registry.mint(path)
        await asyncio.sleep(0)  # interleave with the other turn
        return attachment_registry.resolve(handle)

    async def _main() -> tuple[str | None, str | None]:
        # Each task gets its own copy of the context, so .set() in one does not
        # bleed into the other.
        return await asyncio.gather(_turn("/turn-a.png"), _turn("/turn-b.png"))

    a, b = asyncio.run(_main())
    assert a == "/turn-a.png"
    assert b == "/turn-b.png"
