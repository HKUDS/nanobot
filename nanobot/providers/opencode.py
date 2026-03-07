"""OpenCode Zen provider support - free LLM access without API keys."""

import asyncio
from typing import Any

from loguru import logger
from openai import AsyncOpenAI

from nanobot.providers.base import LLMResponse, ToolCallRequest


# OpenCode Zen endpoint
OPENCODE_ZEN_BASE = "https://opencode.ai/zen/v1"

# Free models available on OpenCode Zen
OPENCODE_FREE_MODELS = {
    "big-pickle": "Big Pickle (GLM-4.6 backend)",
    "gpt-5-nano": "GPT 5 Nano",
    "glm-4.7-free": "GLM 4.7 Free",
    "kimi-k2.5-free": "Kimi K2.5 Free",
}


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
            super().__init__(api_key="opencode-temp-key", **kwargs)
            self.api_key = ""  # Restore empty key - creates "Bearer " header
        else:
            super().__init__(api_key=api_key, **kwargs)


def is_opencode_model(model: str) -> bool:
    """Check if a model is an OpenCode model."""
    return model.startswith("opencode/")


def strip_opencode_prefix(model: str) -> str:
    """Remove opencode/ prefix from model name."""
    return model.replace("opencode/", "")


async def chat_opencode(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    job_id: str | None = None,
    channel: str | None = None,
    chat_id: str | None = None,
) -> LLMResponse:
    """Handle OpenCode Zen chat completion using subclassed OpenAI client.
    
    Retries on 500 errors with exponential backoff and timeline updates.
    """
    # Kimi model prefers temperature 1.0
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

    # Retry configuration
    max_retries = 10
    base_delay = 1.0  # seconds
    
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(**kwargs)
            return _parse_openai_response(response)
            
        except Exception as e:
            error_str = str(e)
            is_500_error = "500" in error_str or "Internal Server Error" in error_str
            
            if is_500_error and attempt < max_retries - 1:
                # Calculate exponential backoff delay
                delay = base_delay * (2 ** attempt)
                logger.warning(f"OpenCode 500 error (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {error_str}")
                
                # Emit timeline update if we have job context
                if job_id and channel and chat_id:
                    try:
                        from nanobot.system.hooks import hook_manager
                        await hook_manager.emit(
                            "agent.tool.execute",
                            tool_name="llm_call",
                            arguments={"status": "retry", "attempt": attempt + 1, "max_retries": max_retries, "delay": delay, "error": "500 Internal Server Error"},
                            channel=channel,
                            chat_id=chat_id,
                            job_id=job_id,
                        )
                    except Exception as hook_error:
                        logger.debug(f"Failed to emit timeline update: {hook_error}")
                
                await asyncio.sleep(delay)
                continue
            else:
                # Final attempt failed or non-500 error
                import traceback
                tb_str = traceback.format_exc()
                error_type = type(e).__name__
                
                # Include retry info in error message if we retried
                retry_info = f" (failed after {attempt + 1} attempts)" if attempt > 0 else ""
                
                full_error = (
                    f"❌ **Error calling OpenCode Zen**{retry_info}\n\n"
                    f"**Type**: `{error_type}`\n"
                    f"**Message**: {error_str}\n\n"
                    f"```\n{tb_str[:500]}\n```"
                )
                return LLMResponse(
                    content=full_error,
                    finish_reason="error",
                )
    
    # Should not reach here, but just in case
    return LLMResponse(
        content="❌ **Error calling OpenCode Zen**: Max retries exceeded",
        finish_reason="error",
    )


def _parse_openai_response(response: Any) -> LLMResponse:
    """Parse OpenAI SDK response into our standard format."""
    import json

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

    # OpenCode models sometimes put content in reasoning_content instead of content
    thinking_content = None
    if hasattr(message, "reasoning_content") and message.reasoning_content:
        thinking_content = message.reasoning_content

    content = message.content
    if not content and thinking_content:
        content = thinking_content
        thinking_content = None

    # Keep raw reasoning_content for forwarding
    reasoning_content = getattr(message, "reasoning_content", None)

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=choice.finish_reason or "stop",
        usage=usage,
        reasoning_content=reasoning_content,
        thinking=thinking_content,
    )
