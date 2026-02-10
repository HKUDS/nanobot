"""Conversation summarization module."""

from nanobot.providers.base import LLMProvider

class Summarizer:
    """Summarizes conversation history."""

    def __init__(self, provider: LLMProvider, model: str | None = None):
        self.provider = provider
        self.model = model

    async def generate_summary(self, recent_messages: list[dict], existing_summary: str | None) -> str:
        """
        Generate a summary of the conversation.

        Args:
            recent_messages: List of recent messages to summarize.
            existing_summary: The existing summary, if any.

        Returns:
            The new summary.
        """
        formatted_messages = []
        for msg in recent_messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            formatted_messages.append(f"{role}: {content}")
        
        messages_str = "\n".join(formatted_messages)

        prompt = (
            "You are a helpful assistant. Please summarize the following conversation history, merging it with the existing summary if provided.\n"
            f"Existing Summary: {existing_summary or 'None'}\n"
            f"Recent Conversation: {messages_str}\n"
            "Output only the new summary."
        )

        response = await self.provider.chat(
            messages=[{"role": "user", "content": prompt}],
            model=self.model
        )

        return response.content
