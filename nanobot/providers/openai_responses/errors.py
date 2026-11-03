"""Explicit unsupported-feature errors at the Responses transport boundary."""

from __future__ import annotations

import json
import re
from typing import cast

COMPACTION_FEATURES = ("context_management", "compact_threshold", "compaction_trigger")
RESPONSES_FEATURES = (
    "responses", "responses api", "responses endpoint", "response api",
    "max_output_tokens", "instructions", "previous_response_id", "input_image",
)


def response_error_details(exc: Exception) -> tuple[object, object]:
    """Read SDK error metadata without treating local exceptions as API errors."""
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    body = (
        getattr(exc, "body", None)
        or getattr(exc, "doc", None)
        or getattr(response, "text", None)
    )
    return status, body


def is_unsupported_feature_error(
    status: object, body: object, features: tuple[str, ...],
) -> bool:
    """Require rejection of a named feature, not an invalid value or incidental mention."""
    if status not in (400, 404, 422):
        return False
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            pass
    if isinstance(body, dict):
        fields = cast(dict[str, object], body)
        error = fields.get("error")
        if isinstance(error, dict):
            fields = cast(dict[str, object], error)
        code = fields.get("code")
        param = fields.get("param")
        if code in ("unknown_parameter", "unsupported_parameter", "unrecognized_parameter"):
            if isinstance(param, str) and re.split(r"[.\[]", param)[0] in features:
                return True
        if code in ("invalid_value", "unsupported_value"):
            return False
        body = fields.get("message")
    if not isinstance(body, str):
        return False
    target = "(?:" + "|".join(re.escape(feature) for feature in features) + ")"
    return bool(re.search(
        rf"(?:unknown|unrecognized|unsupported)\s+"
        rf"(?:parameter|field|request argument(?: supplied)?|input type|endpoint|api)"
        rf"\s*[:=]?\s*[`'\"]?{target}(?!\w)"
        rf"|(?<!\w){target}[`'\"]?\s+(?:is\s+)?(?:not supported|unsupported|not implemented)\b"
        rf"|does not support\s+(?:the\s+)?{target}(?!\w)",
        body, re.IGNORECASE,
    ))
