"""Startup opt-out shared by the two environment-based tracing integrations."""

import os

# langfuse.openai instruments the OpenAI module process-wide. Apply changes at
# startup, not when WebUI saves or an individual model provider is rebuilt.
enabled = True


def requested() -> bool:
    return enabled and bool(os.environ.get("LANGFUSE_SECRET_KEY"))
