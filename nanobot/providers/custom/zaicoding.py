"""Z.ai Coding provider extension.

Z.ai Coding provides coding-focused AI models via OpenAI-compatible API.
"""

from typing import Any

from openai import AsyncOpenAI

# Z.ai Coding configuration
ZAICODING_DEFAULT_BASE = "https://api.z.ai/api/coding/paas/v4"


def is_zaicoding_model(model: str) -> bool:
    """Check if this is a Z.ai Coding model."""
    return model.startswith(("zaicoding/", "zaicodingplan/"))


def resolve_zaicoding_model(model: str) -> str:
    """Strip zaicoding prefix from model name."""
    return model.replace("zaicodingplan/", "").replace("zaicoding/", "")


async def chat_zaicoding(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    api_base: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> tuple[str, list[Any], str, dict, str | None]:
    """Handle Z.ai Coding chat completion.
    
    Returns:
        (content, tool_calls, finish_reason, usage, thinking)
    """
    from nanobot.providers.registry import find_by_name
    
    # Get the Z.ai Coding provider spec to get the default base URL
    spec = find_by_name("zaicodingplan") or find_by_name("zaicoding")
    base_url = api_base or (spec.default_api_base if spec else ZAICODING_DEFAULT_BASE)
    
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
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
    
    thinking = None
    if hasattr(message, "reasoning_content") and message.reasoning_content:
        thinking = message.reasoning_content
    
    content = message.content
    if not content and thinking:
        content = thinking
        thinking = None
    
    return content, tool_calls, choice.finish_reason or "stop", usage, thinking
