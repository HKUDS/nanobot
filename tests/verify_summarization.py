import asyncio
import sys
import os
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.config.loader import load_config
from nanobot.session.manager import SessionManager, Session


class MockProvider(LLMProvider):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        last_msg = messages[-1]["content"]
        if "summarize" in last_msg.lower():
            return LLMResponse(
                content="[Summary: User discussed creating a bot. Details were compressed.]"
            )
        return LLMResponse(content="Mock response")

    def get_default_model(self) -> str:
        return "mock-model"


async def main():
    workspace = Path("/tmp/nanobot_test")
    # Ensure workspace exists
    workspace.mkdir(exist_ok=True)

    bus = MessageBus()

    # Try to load real config
    try:
        config = load_config()
        api_key = config.get_api_key()
        api_base = config.get_api_base()
        model = config.agents.defaults.model

        if api_key:
            print(f"✅ Using Real Provider: {model}")
            provider = LiteLLMProvider(api_key=api_key, api_base=api_base, default_model=model)
        else:
            print("⚠️ No API Key found, using Mock Provider")
            provider = MockProvider()
    except Exception as e:
        print(f"⚠️ Failed to load config ({e}), using Mock Provider")
        provider = MockProvider()

    # Initialize AgentLoop
    agent = AgentLoop(bus=bus, provider=provider, workspace=workspace, max_iterations=1)

    # Create a session and fill it with 45 messages (90 total items)
    session_key = "test:chat_real"
    session = agent.sessions.get_or_create(session_key)
    session.clear()

    print(f"Creating 45 interaction turns (90 messages) in session {session_key}...")
    for i in range(45):
        session.add_message("user", f"Turn {i}: user message content.")
        session.add_message("assistant", f"Turn {i}: assistant response.")

    original_count = len(session.messages)
    print(f"Original message count: {original_count}")

    # Trigger summarization manually
    print("Triggering summarization (this calls the LLM)...")
    await agent._summarize_session(session)

    # Verify results
    new_count = len(session.messages)
    summary = session.summary

    print(f"New message count: {new_count}")
    print(f"Summary: {summary}")

    if new_count == 10 and summary:
        print("✅ Verification SUCCESS: History truncated and summary generated.")
    else:
        print("❌ Verification FAILED.")
        print(f"Expected 10 messages, got {new_count}")
        print(f"Expected summary, got: '{summary}'")


if __name__ == "__main__":
    asyncio.run(main())
