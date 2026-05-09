"""Report context collection from injected CRM read sources."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from crm_mcp_server.redaction import sanitize_error

Reader = Callable[[dict[str, object]], Mapping[str, object]]

SOURCES = (
    "reports",
    "report_related_info",
    "projects",
    "activities",
    "leads",
    "lead_pool",
    "scenarios",
    "immediately_sign_projects",
)
TRANSPORT_DETAIL_PATTERNS = (
    re.compile(r"raw\s+graphql", re.IGNORECASE),
    re.compile(
        r"\b(?:query|mutation|subscription)\b\s*"
        r"(?:[A-Za-z_][A-Za-z0-9_]*\s*)?"
        r"(?:\([^{}]*\)\s*)?\{",
        re.IGNORECASE,
    ),
    re.compile(
        r"\{\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*:\s*)?"
        r"[A-Za-z_][A-Za-z0-9_]*\s*"
        r"(?:\([^{}]*\)\s*)?"
        r"(?:@[A-Za-z_][A-Za-z0-9_]*\s*(?:\([^{}]*\)\s*)?)*"
        r"(?:\{|\})",
        re.IGNORECASE,
    ),
    re.compile(r"\b" + "author" + r"ization\b", re.IGNORECASE),
    re.compile(r"\b" + "bear" + r"er\b", re.IGNORECASE),
    re.compile(r"\bcrm_graphql_token\b", re.IGNORECASE),
    re.compile(r"\b(auth|token)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(endpoint|url)\s*[:=]?\s*\S+\.\S+", re.IGNORECASE),
    re.compile(r"\b((access|api|auth|crm)[\s_-]+)?token\b[\s_-]+secret\b", re.IGNORECASE),
    re.compile(r"\bcookie\b", re.IGNORECASE),
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[\w./?%&=+:-]*)?\b"),
)
TRANSPORT_SECRET_KEYS = (
    "token",
    "access_token",
    "api_token",
    "auth_token",
    "crm_token",
    "auth",
    "cookie",
    "author" + "ization",
    "crm_graphql_token",
    "endpoint",
    "url",
)
SENSITIVE_BUSINESS_KEYS = (
    "amount",
    "budget",
    "quote",
    "price",
    "fee",
    "cost",
    "charge",
    "deal",
    "total",
    "subtotal",
    "contract",
    "revenue",
    "payment",
    "paid",
    "commission",
    "value",
    "phone",
    "mobile",
    "email",
    "contact",
    "address",
    "合同金额",
)
REDACTED_TRANSPORT_DETAIL = "[redacted transport detail]"
SENSITIVE_BUSINESS_DETAIL_PATTERNS = (
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b\d{10}\b"),
    re.compile(r"\b1\d{10}\b"),
    re.compile(r"\b1\d{2}[\s.-]\d{4}[\s.-]\d{4}\b"),
    re.compile(r"\+\d{10,15}\b"),
    re.compile(r"(?:\+\d{1,3}\s*)?\(\d{3}\)\s*\d{3}-\d{4}"),
    re.compile(r"\b0\d{2,3}-\d{7,8}\b"),
    re.compile(r"(?:\+\d{1,3}[\s.-]+\d[\d\s().-]{7,}\d|\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b)"),
    re.compile(r"\b(?:phone|email|contact|address)\b\s*[:：]?\s*[^.。;；,，\n]+", re.IGNORECASE),
    re.compile(
        r"\b(?:amount(?:_\w+)?|budget|quote|price|fee|cost|charge|deal(?:\s+(?:total|size))?|total|subtotal|contract(?:[\s_]+value)?|revenue|payment|paid|commission|value)\b"
        r"\s*(?:is\s+)?[:：=]?\s*[¥￥$€]?\s*[\d,]+(?:\.\d+)?",
        re.IGNORECASE,
    ),
    re.compile(r"(?:合同金额|预算|金额|报价)\s*[:：=]?\s*[¥￥$€]?\s*[\d,]+(?:\.\d+)?", re.IGNORECASE),
    re.compile(r"[¥￥$€]\s*\d[\d,]*(?:\.\d+)?"),
)
REDACTED_BUSINESS_DETAIL = "[redacted business detail]"


def collect_sales_daily_context(
    *,
    window: Mapping[str, object],
    scope: Mapping[str, object],
    options: Mapping[str, object] | None = None,
    readers: Mapping[str, Reader] | None = None,
) -> dict[str, object]:
    return _collect_context(
        context_type="sales_daily",
        window=window,
        scope=scope,
        options=options,
        readers=readers,
    )


def collect_sales_weekly_context(
    *,
    window: Mapping[str, object],
    scope: Mapping[str, object],
    options: Mapping[str, object] | None = None,
    readers: Mapping[str, Reader] | None = None,
) -> dict[str, object]:
    return _collect_context(
        context_type="sales_weekly",
        window=window,
        scope=scope,
        options=options,
        readers=readers,
    )


def collect_presales_weekly_context(
    *,
    window: Mapping[str, object],
    scope: Mapping[str, object],
    options: Mapping[str, object] | None = None,
    readers: Mapping[str, Reader] | None = None,
) -> dict[str, object]:
    return _collect_context(
        context_type="presales_weekly",
        window=window,
        scope=scope,
        options=options,
        readers=readers,
    )


def _collect_context(
    *,
    context_type: str,
    window: Mapping[str, object],
    scope: Mapping[str, object],
    options: Mapping[str, object] | None,
    readers: Mapping[str, Reader] | None,
) -> dict[str, object]:
    safe_window = _safe_window(window)
    safe_scope = _safe_scope(scope)
    safe_options = options if isinstance(options, Mapping) else {}
    request = {
        "window": safe_window,
        "scope": safe_scope,
        "options": {"max_records": _requested_max_records(safe_options)},
    }
    safe_readers = readers if isinstance(readers, Mapping) else {}

    records: dict[str, list[dict[str, object]]] = {}
    source_counts: dict[str, int] = {}
    source_refs: list[Mapping[str, object]] = []
    unavailable_sources: list[dict[str, object]] = []

    for source in SOURCES:
        result = _read_source(source, safe_readers.get(source), request)
        if result["errors"]:
            records[source] = []
            source_counts[source] = 0
            unavailable_sources.append({"source": source, "errors": result["errors"]})
            continue

        source_records = _records(result)
        records[source] = source_records
        source_counts[source] = len(source_records)
        source_refs.extend(_source_refs(result))

    return _sanitize_transport_detail({
        "context_type": context_type,
        "window": safe_window,
        "scope": safe_scope,
        "records": records,
        "source_refs": _dedupe_source_refs(source_refs),
        "unavailable_sources": unavailable_sources,
        "diagnostics": {
            "status": "OK" if not unavailable_sources else "INCONCLUSIVE",
            "read_only": True,
            "mutations_allowed": False,
            "mutation_used": False,
            "source_counts": source_counts,
        },
    })


def _read_source(
    source: str, reader: Reader | None, request: dict[str, object]
) -> Mapping[str, object]:
    if reader is None:
        return {"records": [], "source_refs": [], "errors": [sanitize_error("config_missing")]}
    try:
        return reader(request)
    except Exception:
        return {"records": [], "source_refs": [], "errors": [sanitize_error("crm_unavailable")]}


def _safe_window(window: Mapping[str, object]) -> dict[str, object]:
    return {"start": _safe_string(window.get("start")), "end": _safe_string(window.get("end"))}


def _safe_scope(scope: Mapping[str, object]) -> dict[str, object]:
    return {
        "scope_id": _safe_string(scope.get("scope_id")),
        "owner_ids": _safe_string_list(scope.get("owner_ids")),
        "group_ids": _safe_string_list(scope.get("group_ids")),
    }


def _requested_max_records(options: Mapping[str, object]) -> int:
    max_records = options.get("max_records", 50)
    return max_records if isinstance(max_records, int) else 50


def _records(result: Mapping[str, object]) -> list[dict[str, object]]:
    records = result.get("records")
    if not isinstance(records, list):
        return []
    return [dict(record) for record in records if isinstance(record, Mapping)]


def _source_refs(result: Mapping[str, object]) -> list[Mapping[str, object]]:
    source_refs = result.get("source_refs")
    if not isinstance(source_refs, list):
        return []
    return [source_ref for source_ref in source_refs if isinstance(source_ref, Mapping)]


def _dedupe_source_refs(source_refs: list[Mapping[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for source_ref in source_refs:
        source_ref_id = source_ref.get("id")
        if not isinstance(source_ref_id, str) or source_ref_id in seen:
            continue
        seen.add(source_ref_id)
        deduped.append(
            {
                "id": source_ref_id,
                "system": _safe_string(source_ref.get("system")),
                "query": _safe_string(source_ref.get("query")),
                "entity_type": _safe_string(source_ref.get("entity_type")),
                "source_id": _safe_string(source_ref.get("source_id")),
                "fields": _safe_string_list(source_ref.get("fields")),
            }
        )
    return deduped


def _safe_string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _safe_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _sanitize_transport_detail(value: object) -> object:
    return sanitize_transport_detail(value)


def sanitize_transport_detail(value: object) -> object:
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in TRANSPORT_DETAIL_PATTERNS):
            return REDACTED_TRANSPORT_DETAIL
        return _sanitize_sensitive_business_details(value)
    if isinstance(value, list):
        return [sanitize_transport_detail(item) for item in value]
    if isinstance(value, Mapping):
        sanitized: dict[object, object] = {}
        for key, item in value.items():
            is_secret_key = _is_transport_secret_key(key)
            is_sensitive_business_key = _is_sensitive_business_key(key)
            if is_secret_key:
                sanitized[REDACTED_TRANSPORT_DETAIL] = REDACTED_TRANSPORT_DETAIL
            elif is_sensitive_business_key:
                sanitized[REDACTED_BUSINESS_DETAIL] = REDACTED_BUSINESS_DETAIL
            else:
                sanitized[sanitize_transport_detail(key)] = sanitize_transport_detail(item)
        return sanitized
    return value


def _sanitize_sensitive_business_details(value: str) -> str:
    sanitized = value
    for pattern in SENSITIVE_BUSINESS_DETAIL_PATTERNS:
        sanitized = pattern.sub(REDACTED_BUSINESS_DETAIL, sanitized)
    return sanitized


def _is_transport_secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized_key = key.casefold().replace("-", "_")
    compact_key = re.sub(r"[^a-z0-9]", "", normalized_key)
    return (
        normalized_key in TRANSPORT_SECRET_KEYS
        or normalized_key.endswith("_endpoint")
        or normalized_key.endswith("_url")
        or normalized_key.endswith("url")
        or any(marker in compact_key for marker in ("token", "auth", "cookie", "endpoint", "url"))
    )


def _is_sensitive_business_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized_key = key.casefold().replace("-", "_")
    return any(marker in normalized_key for marker in SENSITIVE_BUSINESS_KEYS)
