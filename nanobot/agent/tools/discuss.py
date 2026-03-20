"""Discuss tool for orchestrating multi-agent discussions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    pass


class DiscussTool(Tool):
    """Orchestrate a multi-round discussion between named agents."""

    def __init__(
        self,
        run_callback: Callable[[str, str, str, str], Awaitable[str]],
        list_callback: Callable[[], list[str]],
    ):
        self._run = run_callback  # (agent_name, task, channel, chat_id) -> result
        self._list = list_callback
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    @property
    def name(self) -> str:
        return "discuss"

    @property
    def description(self) -> str:
        return (
            "Start a multi-round discussion between named agents on a given topic. "
            "Each agent takes turns responding, seeing the full discussion history. "
            "Use this when the user wants agents to debate, brainstorm, or review together."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of agents to participate in the discussion (at least 2)",
                },
                "topic": {
                    "type": "string",
                    "description": "The discussion topic or question",
                },
                "max_rounds": {
                    "type": "integer",
                    "description": "Maximum number of discussion rounds (default: 3)",
                },
            },
            "required": ["agents", "topic"],
        }

    async def execute(
        self, agents: list[str], topic: str, max_rounds: int = 3, **kwargs: Any
    ) -> str:
        available = set(self._list())
        if len(agents) < 2:
            return "Discussion requires at least 2 agents."
        missing = [a for a in agents if a not in available]
        if missing:
            return f"Agent(s) not found: {', '.join(missing)}. Available: {', '.join(available)}"

        max_rounds = min(max_rounds, 10)  # hard cap
        transcript: list[dict[str, str]] = []

        for round_num in range(max_rounds):
            for agent_name in agents:
                # Build the prompt with full discussion context
                prompt = self._build_round_prompt(agent_name, topic, transcript, round_num)
                response = await self._run(
                    agent_name, prompt, self._origin_channel, self._origin_chat_id,
                )
                transcript.append({"agent": agent_name, "content": response})

        return self._format_transcript(topic, transcript)

    @staticmethod
    def _build_round_prompt(
        agent_name: str,
        topic: str,
        transcript: list[dict[str, str]],
        round_num: int,
    ) -> str:
        parts = [f"You are participating in a group discussion.\n\nTopic: {topic}"]
        if transcript:
            parts.append("\n--- Discussion so far ---")
            for entry in transcript:
                parts.append(f"\n**{entry['agent']}**: {entry['content']}")
            parts.append("\n--- End of discussion ---")
        parts.append(
            f"\nIt's your turn (round {round_num + 1}). "
            "Share your perspective, respond to others' points, or build on their ideas. "
            "If you believe the discussion has reached a conclusion, say so clearly."
        )
        return "\n".join(parts)

    @staticmethod
    def _format_transcript(topic: str, transcript: list[dict[str, str]]) -> str:
        lines = [f"## Discussion: {topic}\n"]
        for i, entry in enumerate(transcript):
            lines.append(f"**{entry['agent']}**: {entry['content']}\n")
        lines.append("---\n*Discussion ended.*")
        return "\n".join(lines)
