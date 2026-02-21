"""Kilocode provider extension.

Kilocode provides FREE AI models via Z.ai API with custom headers.
"""

from typing import Any

from openai import AsyncOpenAI

# Kilocode configuration - OpenAI-compatible endpoint via KiloCode gateway
KILOCODE_DEFAULT_BASE = "https://api.kilo.ai/api/openrouter"

def is_kilocode_model(model: str) -> bool:
    """Check if this is a Kilocode model."""
    return model.startswith(("kilo/", "kilocode/"))


def resolve_kilocode_model(model: str) -> str:
    """Strip kilocode prefix from model name."""
    for prefix in ["kilo/", "kilocode/"]:
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


async def chat_kilocode(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    api_base: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> tuple[str, list[Any], str, dict, str | None]:
    """Handle Kilocode chat completion.

    Returns:
        (content, tool_calls, finish_reason, usage, thinking)
    """
    base_url = api_base or KILOCODE_DEFAULT_BASE

    # Kilocode requires custom headers
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers={
            "Authorization": f"Bearer {api_key}",
            "x-api-key": api_key,
            "X-KILOCODE-EDITORNAME": "custom",
        },
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

    # Handle empty choices (API error)
    if not response.choices:
        error_msg = "Unknown API error"
        if hasattr(response, "error") and response.error:
            error_msg = response.error.get("message", str(response.error))
        raise ValueError(f"Kilocode API error: {error_msg}")

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
    # Try both 'reasoning' (OpenRouter format) and 'reasoning_content' (some providers)
    if hasattr(message, "reasoning") and message.reasoning:
        thinking = message.reasoning
    elif hasattr(message, "reasoning_content") and message.reasoning_content:
        thinking = message.reasoning_content

    content = message.content
    if not content and thinking:
        content = thinking
        thinking = None

    return content, tool_calls, choice.finish_reason or "stop", usage, thinking
