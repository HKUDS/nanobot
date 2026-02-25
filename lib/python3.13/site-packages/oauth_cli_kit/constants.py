"""Default provider settings and constants."""

from __future__ import annotations

from oauth_cli_kit.providers.openai_codex import OPENAI_CODEX_PROVIDER

SUCCESS_HTML = (
    "<!doctype html>"
    "<html lang=\"en\">"
    "<head>"
    "<meta charset=\"utf-8\" />"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
    "<title>Authentication successful</title>"
    "</head>"
    "<body>"
    "<p>Authentication successful. Return to your terminal to continue.</p>"
    "</body>"
    "</html>"
)

# 兼容性：历史上从 oauth_cli_kit.constants 导入 provider。
__all__ = [
    "SUCCESS_HTML",
    "OPENAI_CODEX_PROVIDER",
]
