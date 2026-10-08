"""Temporary input compatibility for the former OpenAI API selector.

Keep this conversion for the first two releases shipping it; remove it before
the third release. The removal checklist is in docs/releasing.md.
"""

from typing import Any


def migrate_legacy_provider_api(
    values: dict[str, Any], *, provider_name: str,
) -> dict[str, Any]:
    """Consume old input keys; all callers receive the current API declaration."""
    if "apiType" not in values and "api_type" not in values and "apitype" not in values:
        return values
    migrated = dict(values)
    # Case-insensitive settings sources normalize the former apiType env alias.
    legacy = migrated.pop("apiType", migrated.get("api_type", migrated.get("apitype", "auto")))
    migrated.pop("api_type", None)
    migrated.pop("apitype", None)
    if "api" in migrated:
        return migrated
    if legacy not in ("auto", "chat_completions", "responses"):
        raise ValueError("apiType must be auto, chat_completions, or responses")
    if legacy == "auto":
        migrated["api"] = None
        return migrated
    if provider_name != "openai":
        raise ValueError("apiType is only supported for providers.openai")
    migrated["api"] = {"supported_apis": [legacy], "preferred_api": legacy}
    return migrated
