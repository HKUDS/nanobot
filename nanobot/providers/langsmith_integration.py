"""Optional LangSmith tracing for native provider clients."""

from __future__ import annotations

import importlib.util
import os
from typing import Any

from loguru import logger


def _configure() -> bool:
    """Prepare LangSmith's environment and report whether it is available."""
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        return False
    if importlib.util.find_spec("langsmith") is None:
        logger.warning(
            "LANGSMITH_API_KEY is set but langsmith is not installed; "
            "run `pip install nanobot-ai[langsmith]` to enable tracing"
        )
        return False

    os.environ.setdefault("LANGSMITH_TRACING", "true")
    return True


def wrap_openai_client(client: Any) -> Any:
    """Wrap an OpenAI-compatible client when LangSmith is configured."""
    if not _configure():
        return client
    try:
        from langsmith.wrappers import wrap_openai

        return wrap_openai(client)
    except Exception as exc:
        logger.warning("Unable to enable LangSmith OpenAI tracing: {}", exc)
        return client


def wrap_anthropic_client(client: Any) -> Any:
    """Wrap an Anthropic client when LangSmith is configured."""
    if not _configure():
        return client
    try:
        from langsmith.wrappers import wrap_anthropic

        return wrap_anthropic(client)
    except Exception as exc:
        logger.warning("Unable to enable LangSmith Anthropic tracing: {}", exc)
        return client
