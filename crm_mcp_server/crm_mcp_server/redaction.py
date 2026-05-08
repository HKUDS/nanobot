"""Sanitized output helpers for CRM MCP tools."""

from __future__ import annotations

SAFE_ERROR_MESSAGES: dict[str, str] = {
    "invalid_request": "The request is invalid.",
    "config_missing": "Required runtime configuration is missing.",
    "crm_unavailable": "The CRM service is unavailable.",
    "unauthorized_or_forbidden": "CRM access is unauthorized or forbidden.",
    "graphql_error": "The CRM query returned an error.",
    "pagination_limit_reached": "The pagination safety limit was reached.",
    "normalization_failed": "The CRM response could not be normalized.",
    "missing_required_fields": "The CRM response is missing required fields.",
    "empty_result": "The CRM query returned no records.",
    "rate_limited": "The CRM service rate limit was reached.",
    "invalid_response": "The CRM response shape is invalid.",
    "operation_data_missing": "The CRM response is missing the requested operation data.",
    "records_field_missing": "The CRM response is missing the records field.",
    "internal_error": "An internal error occurred.",
}

RETRYABLE_CATEGORIES: set[str] = {
    "crm_unavailable",
    "rate_limited",
}


def sanitize_error(category: str, raw_message: str | None = None) -> dict[str, object]:
    """Return a fixed safe ToolError shape without using raw message text."""

    safe_category = category if category in SAFE_ERROR_MESSAGES else "internal_error"
    return {
        "category": safe_category,
        "message": SAFE_ERROR_MESSAGES[safe_category],
        "retryable": safe_category in RETRYABLE_CATEGORIES,
    }


def sanitize_errors(categories: list[str]) -> list[dict[str, object]]:
    """Return sanitized ToolError objects for category names."""

    return [sanitize_error(category) for category in categories]
