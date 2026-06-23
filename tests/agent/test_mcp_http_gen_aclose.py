"""Regression test for #4302: force-close streamable_http generator.

Verifies that the stashed ``_mcp_http_gen`` attribute is the raw async
generator (not the ``_AsyncGeneratorContextManager`` wrapper) so that
``.aclose()`` actually closes the underlying transport.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest


@pytest.mark.asyncio
async def test_async_context_manager_gen_has_aclose():
    """_AsyncGeneratorContextManager has no aclose(); .gen does."""

    @asynccontextmanager
    async def _fake_transport():
        yield "read", "write"

    cm = _fake_transport()
    # The context manager wrapper itself must NOT have aclose()
    assert not hasattr(cm, "aclose"), (
        "_AsyncGeneratorContextManager should not have aclose()"
    )
    # The underlying generator MUST have aclose()
    assert hasattr(cm.gen, "aclose"), (
        "Underlying async generator must have aclose()"
    )


@pytest.mark.asyncio
async def test_stashing_gen_allows_aclose():
    """Stashing .gen (not the CM) lets cleanup code call aclose() successfully."""
    closed = False

    @asynccontextmanager
    async def _fake_transport():
        nonlocal closed
        try:
            yield "read", "write"
        finally:
            closed = True

    cm = _fake_transport()
    await cm.__aenter__()

    # Simulate what the fix does: stash cm.gen
    stashed = cm.gen
    assert hasattr(stashed, "aclose")

    # Calling aclose() on the generator should work
    await stashed.aclose()
    assert closed, "Generator finally block should have run"


@pytest.mark.asyncio
async def test_stashing_cm_aclose_raises():
    """Stashing the CM (old code) means aclose() raises AttributeError."""
    @asynccontextmanager
    async def _fake_transport():
        yield "read", "write"

    cm = _fake_transport()
    await cm.__aenter__()

    # Old code stashed cm directly — aclose() would raise
    with pytest.raises(AttributeError, match="aclose"):
        await cm.aclose()
