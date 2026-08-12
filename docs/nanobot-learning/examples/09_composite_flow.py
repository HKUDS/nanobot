"""Connect nanobot's local boundaries without an external LLM call."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


@tool_parameters(
    {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
)
class FirstSentenceTool(Tool):
    @property
    def name(self) -> str:
        return "first_sentence"

    @property
    def description(self) -> str:
        return "Return the first sentence of text."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: str) -> str:
        return kwargs["text"].split("。", maxsplit=1)[0]


async def main() -> None:
    with TemporaryDirectory() as directory:
        workspace = Path(directory)
        bus = MessageBus()
        memory = MemoryStore(workspace)
        context = ContextBuilder(workspace, timezone="Asia/Shanghai")
        tools = ToolRegistry()
        tools.register(FirstSentenceTool())

        await bus.publish_inbound(
            InboundMessage(
                channel="lesson",
                sender_id="student",
                chat_id="flow",
                content="nanobot 使用异步消息总线。它把渠道和 AgentLoop 解耦。",
            )
        )
        inbound = await bus.consume_inbound()
        messages = context.build_messages([], inbound.content, workspace=workspace)
        summary = await tools.execute("first_sentence", {"text": inbound.content})
        memory.append_history(f"summary: {summary}", session_key=inbound.session_key)
        await bus.publish_outbound(
            OutboundMessage(channel=inbound.channel, chat_id=inbound.chat_id, content=summary)
        )
        outbound = await bus.consume_outbound()

        print(f"session_key={inbound.session_key}")
        print(f"prompt_messages={len(messages)}")
        print(f"tool_result={summary}")
        print(f"outbound={outbound.content}")
        print(f"history_exists={memory.history_file.exists()}")


if __name__ == "__main__":
    asyncio.run(main())
