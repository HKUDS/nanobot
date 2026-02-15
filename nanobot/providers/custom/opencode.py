"""OpenCode Zen provider extension.

OpenCode Zen provides free AI models without authentication.
Requires empty api_key which sends "Authorization: Bearer " header.
"""

from typing import Any

from openai import AsyncOpenAI

# OpenCode Zen configuration
OPENCODE_ZEN_BASE = "https://opencode.ai/zen/v1"
OPENCODE_FREE_MODELS = {
    "big-pickle": "Big Pickle (GLM-4.6 backend)",
    "gpt-5-nano": "GPT 5 Nano",
    "glm-4.7-free": "GLM 4.7 Free",
    "kimi-k2.5-free": "Kimi K2.5 Free",
}


def is_opencode_model(model: str, api_base: str | None = None) -> bool:
    """Check if this is an OpenCode Zen model."""
    return model.startswith("opencode/") or (api_base and "opencode.ai" in api_base)


def resolve_opencode_model(model: str) -> tuple[str, str | None]:
    """Resolve OpenCode model name.
    
    Returns:
        (resolved_model, opencode_model_name or None)
    """
    if model.startswith("opencode/"):
        opencode_model = model.replace("opencode/", "")
        # Use hosted_vllm prefix for LiteLLM to accept custom endpoint
        return f"hosted_vllm/{opencode_model}", opencode_model
    return model, None


class OpenCodeAsyncOpenAI(AsyncOpenAI):
    """AsyncOpenAI subclass that accepts empty API keys for OpenCode Zen.

    OpenCode Zen requires api_key="" which sends "Authorization: Bearer " header.
    The standard OpenAI SDK rejects empty api_key in __init__, so we override it.
    """

    def __init__(self, *, api_key: str | None = None, **kwargs) -> None:
        """Override to allow empty api_key for OpenCode Zen."""
        is_opencode = kwargs.get("base_url", "").startswith("https://opencode.ai")

        if is_opencode and api_key == "":
            # Bypass OpenAI's validation by temporarily setting a non-empty key
            # then restoring it after parent init
            super().__init__(api_key="opencode-temp-key", **kwargs)
            self.api_key = ""  # Restore empty key - this creates "Bearer " header
        else:
            super().__init__(api_key=api_key, **kwargs)


async def chat_opencode(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> tuple[str, list[Any], str, dict, str | None]:
    """Handle OpenCode Zen chat completion.
    
    Returns:
        (content, tool_calls, finish_reason, usage, thinking)
    """
    from nanobot.providers.litellm_provider import LiteLLMProvider
    
    # Kimi K2.5 requires temperature 1.0
    if "kimi-k2.5" in model.lower():
        temperature = 1.0
    
    client = OpenCodeAsyncOpenAI(
        api_key="",  # Empty string - creates "Authorization: Bearer " header
        base_url=OPENCODE_ZEN_BASE,
    )
    
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    
    response = await client.chat.completions.create(**kwargs)
    
    # Parse response
    choice = response.choices[0]
    message = choice.message
    
    tool_calls = []
    if hasattr(message, "tool_calls") and message.tool_calls:
        import json
        for tc in message.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": args,
            })
    
    usage = {}
    if hasattr(response, "usage") and response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    
    # OpenCode models sometimes put content in reasoning_content
    thinking = None
    if hasattr(message, "reasoning_content") and message.reasoning_content:
        thinking = message.reasoning_content
    
    content = message.content
    if not content and thinking:
        content = thinking
        thinking = None
    
    return content, tool_calls, choice.finish_reason or "stop", usage, thinking
