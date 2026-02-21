"""Kilo Code provider support - OpenAI-compatible with custom headers."""

from typing import Any

from openai import AsyncOpenAI

from nanobot.providers.base import LLMResponse, ToolCallRequest


# Kilo Code endpoint
KILOCODE_BASE = "https://api.kilo.ai/api/openrouter"


class KiloCodeAsyncOpenAI(AsyncOpenAI):
    """AsyncOpenAI subclass that adds Kilo Code custom headers."""

    def __init__(self, *, api_key: str | None = None, **kwargs) -> None:
        """Override to add Kilo Code specific headers."""
        super().__init__(api_key=api_key, **kwargs)
        # Add custom headers for Kilo Code API
        self.default_headers.update({
            "x-api-key": api_key or "",
            "X-KILOCODE-EDITORNAME": "custom",
        })


def is_kilocode_model(model: str) -> bool:
    """Check if a model is a Kilo Code model."""
    return model.startswith("kilo/")


def strip_kilocode_prefix(model: str) -> str:
    """Remove kilo/ prefix from model name.

    For example: 'kilo/z-ai/glm-5:free' -> 'z-ai/glm-5:free'
    """
    return model.replace("kilo/", "")


async def chat_kilocode(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    api_key: str | None = None,
) -> LLMResponse:
    """Handle Kilo Code chat completion using subclassed OpenAI client.

    model can be:
    - Full model ID like 'kilo/z-ai/glm-5:free'
    - Already stripped model like 'z-ai/glm-5:free'
    """
    try:
        # Strip 'kilo/' prefix if present
        model = strip_kilocode_prefix(model)

        client = KiloCodeAsyncOpenAI(
            api_key=api_key or "",
            base_url=KILOCODE_BASE,
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
        return _parse_openai_response(response)

    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        error_type = type(e).__name__
        error_msg = str(e)

        full_error = (
            f"❌ **Error calling Kilo Code**\n\n"
            f"**Type**: `{error_type}`\n"
            f"**Message**: {error_msg}\n\n"
            f"```\n{tb_str[:500]}\n```"
        )
        return LLMResponse(
            content=full_error,
            finish_reason="error",
        )


def _parse_openai_response(response: Any) -> LLMResponse:
    """Parse OpenAI SDK response into our standard format."""
    import json

    # Handle error responses where choices is None
    if not response.choices:
        error_msg = getattr(response, 'error', None) or "Unknown error: no choices returned"
        return LLMResponse(
            content=f"❌ API Error: {error_msg}",
            finish_reason="error",
        )

    choice = response.choices[0]
    message = choice.message

    tool_calls = []
    if hasattr(message, "tool_calls") and message.tool_calls:
        for tc in message.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}

            tool_calls.append(ToolCallRequest(
                id=tc.id,
                name=tc.function.name,
                arguments=args,
            ))

    usage = {}
    if hasattr(response, "usage") and response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    # Extract thinking/reasoning content
    thinking_content = None
    if hasattr(message, "reasoning_content") and message.reasoning_content:
        thinking_content = message.reasoning_content
    elif hasattr(message, "thinking") and message.thinking:
        thinking_content = message.thinking

    content = message.content
    if not content and thinking_content:
        content = thinking_content
        thinking_content = None

    reasoning_content = getattr(message, "reasoning_content", None)

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=choice.finish_reason or "stop",
        usage=usage,
        reasoning_content=reasoning_content,
        thinking=thinking_content,
    )
