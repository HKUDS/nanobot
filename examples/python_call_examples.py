"""
Python Call Channel — Usage Examples
=====================================

The ``python_call`` channel lets you interact with nanobot programmatically
from any Python code.  Think of it as turning the agent into an async function:
no webhooks, no message queues — just ``await``.

Enable it in ``~/.nanobot/config.json``:

    {
      "channels": {
        "python_call": {
          "enabled": true
        }
      }
    }

Then use any of the patterns below.
"""

from __future__ import annotations

import asyncio

# ---------------------------------------------------------------------------
# Helper: get the python_call channel from a running nanobot gateway
# ---------------------------------------------------------------------------


async def get_channel():
    """
    Boot nanobot and return the python_call channel.

    In production you would typically start the gateway separately
    (``nanobot gateway``) and obtain the channel from the running
    ChannelManager.  This helper is a self-contained shortcut for
    examples and scripts.
    """
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.loader import load_config

    config = load_config()
    bus = MessageBus()
    manager = ChannelManager(config, bus)
    await manager.start_all()
    channel = manager.get_channel("python_call")
    return channel, manager


# ===================================================================
# Example 1 — One-off call (no session persistence)
# ===================================================================


async def example_one_off():
    """Send a single message and get a response."""
    channel, manager = await get_channel()
    try:
        response = await channel.call("What is 2 + 2?", timeout=30.0)
        print("Agent:", response)
    finally:
        await manager.stop_all()


# ===================================================================
# Example 2 — Persistent session (conversation history preserved)
# ===================================================================


async def example_session():
    """
    Use ``session_id`` to keep conversation context across calls.
    The agent will remember prior messages within the same session.
    """
    channel, manager = await get_channel()
    try:
        await channel.call(
            "My name is Alice.",
            session_id="alice",
            timeout=30.0,
        )
        reply = await channel.call(
            "What is my name?",
            session_id="alice",
            timeout=30.0,
        )
        print("Agent:", reply)  # Should mention "Alice"
    finally:
        await manager.stop_all()


# ===================================================================
# Example 3 — Config overrides via metadata
# ===================================================================


async def example_metadata_override():
    """
    Pass ``metadata`` to override agent config on the fly —
    e.g. a custom system prompt or model.
    """
    channel, manager = await get_channel()
    try:
        response = await channel.call(
            "Hello, how are you?",
            session_id="translator",
            metadata={"system_prompt": "You are a French translator. Reply only in French."},
            timeout=30.0,
        )
        print("Agent (French):", response)
    finally:
        await manager.stop_all()


# ===================================================================
# Example 4 — Embed in a web app (FastAPI)
# ===================================================================

"""
from contextlib import asynccontextmanager
from fastapi import FastAPI

channel = None

@asynccontextmanager
async def lifespan(app):
    global channel
    channel, manager = await get_channel()
    yield
    await manager.stop_all()

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(msg: str, user_id: str = "anonymous"):
    reply = await channel.call(
        msg,
        sender_id=user_id,
        session_id=user_id,   # each user gets their own session
        timeout=60.0,
    )
    return {"reply": reply}
"""


# ===================================================================
# Example 5 — Batch processing with asyncio.gather
# ===================================================================


async def example_batch():
    """Process multiple inputs concurrently."""
    channel, manager = await get_channel()
    try:
        documents = [
            "Python is a programming language.",
            "Rust is a systems programming language.",
            "Go is designed for concurrency.",
        ]
        tasks = [
            channel.call(
                f"Summarize in one sentence: {doc}",
                session_id=f"batch-{i}",
                timeout=60.0,
            )
            for i, doc in enumerate(documents)
        ]
        results = await asyncio.gather(*tasks)
        for doc, summary in zip(documents, results):
            print(f"  {doc[:30]}... -> {summary}")
    finally:
        await manager.stop_all()


# ===================================================================
# Example 6 — Multi-agent chaining (pipeline)
# ===================================================================


async def example_pipeline():
    """
    Chain multiple agent calls where the output of one becomes
    the input of the next — like Unix pipes.
    """
    channel, manager = await get_channel()
    try:
        # Step 1: translate
        translation = await channel.call(
            "今天天气真好",
            session_id="translator",
            metadata={"system_prompt": "Translate the input to English. Reply with only the translation."},
            timeout=30.0,
        )
        print("Translation:", translation)

        # Step 2: review
        review = await channel.call(
            f"Is this translation accurate? Original: '今天天气真好', Translation: '{translation}'",
            session_id="reviewer",
            metadata={"system_prompt": "You are a translation reviewer. Reply with a brief assessment."},
            timeout=30.0,
        )
        print("Review:", review)
    finally:
        await manager.stop_all()


# ===================================================================
# Example 7 — Timeout handling
# ===================================================================


async def example_timeout():
    """Gracefully handle agent timeouts."""
    channel, manager = await get_channel()
    try:
        try:
            response = await channel.call(
                "Write a very long essay about the universe.",
                timeout=5.0,  # short timeout for demo
            )
            print("Agent:", response)
        except asyncio.TimeoutError:
            print("Agent did not respond in time — try a longer timeout or simpler prompt.")
    finally:
        await manager.stop_all()


# ===================================================================
# Example 8 — Testing in CI / pytest
# ===================================================================

"""
import pytest

@pytest.fixture
async def channel():
    ch, manager = await get_channel()
    yield ch
    await manager.stop_all()

@pytest.mark.asyncio
async def test_greeting(channel):
    reply = await channel.call("Hello!", timeout=10.0)
    assert len(reply) > 0

@pytest.mark.asyncio
async def test_math(channel):
    reply = await channel.call("What is 1 + 1? Reply with just the number.", timeout=10.0)
    assert "2" in reply
"""


# ===================================================================
# Run all examples
# ===================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Example 1: One-off call")
    print("=" * 60)
    asyncio.run(example_one_off())

    print("\n" + "=" * 60)
    print("Example 2: Persistent session")
    print("=" * 60)
    asyncio.run(example_session())

    print("\n" + "=" * 60)
    print("Example 3: Metadata override (French translator)")
    print("=" * 60)
    asyncio.run(example_metadata_override())

    print("\n" + "=" * 60)
    print("Example 4: Batch processing")
    print("=" * 60)
    asyncio.run(example_batch())

    print("\n" + "=" * 60)
    print("Example 5: Multi-agent pipeline")
    print("=" * 60)
    asyncio.run(example_pipeline())

    print("\n" + "=" * 60)
    print("Example 6: Timeout handling")
    print("=" * 60)
    asyncio.run(example_timeout())
