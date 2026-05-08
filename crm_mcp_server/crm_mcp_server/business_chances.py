"""Sanitized read-only business chance listing with mocked GraphQL responses."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from crm_mcp_server.graphql import build_read_operation
from crm_mcp_server.real_smoke import RealGraphQLSmokeTransport, load_real_smoke_config_from_env
from crm_mcp_server.redaction import sanitize_errors

DEFAULT_PAGE_SIZE = 50
MAX_RECORDS_CAP = 200
MAX_PAGES = 5
OPERATION_NAME = "list_business_chance"
SOURCE_REF_FIELDS = [
    "id",
    "project_id",
    "status",
    "apply_status",
    "owner.id",
    "owner.name",
    "due_at",
    "created_at",
    "updated_at",
]


class BusinessChanceTransport(Protocol):
    def execute(self, operation_name: str, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        """Execute a mocked GraphQL operation."""


def crm_list_business_chances(
    request: Mapping[str, Any],
    *,
    transport: BusinessChanceTransport | None = None,
    runtime_enabled: bool = False,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = MAX_PAGES,
) -> dict[str, object]:
    """Return sanitized business chance records from list_business_chance responses."""

    max_records = _requested_max_records(request)
    validation_reason = _validate_request(request, max_records=max_records)
    if validation_reason is not None:
        return _result(
            records=[],
            source_refs=[],
            errors=["invalid_request"],
            diagnostics=_diagnostics(
                status="ERROR",
                reason=validation_reason,
                records_returned=0,
                pages_read=0,
                max_records=max_records,
                runtime_enabled=runtime_enabled,
                transport=transport,
            ),
        )

    if transport is None:
        if not runtime_enabled:
            return _config_missing_result(max_records=max_records, auth_mode="mock")
        config = load_real_smoke_config_from_env()
        if config is None:
            return _config_missing_result(
                max_records=max_records,
                auth_mode="bearer",
                runtime_enabled=False,
                endpoint_configured=False,
                token_configured=False,
            )
        transport = RealGraphQLSmokeTransport(config=config)

    records: list[dict[str, object]] = []
    source_refs: list[dict[str, object]] = []
    pages_read = 0
    skip = 0
    limit = min(page_size, max_records)
    reached_page_limit = False

    while len(records) < max_records and pages_read < max_pages:
        response = _read_page(request, transport=transport, skip=skip, limit=limit)
        pages_read += 1
        transport_error = _transport_error_category(transport)
        http_status = _http_status_category(transport)
        if http_status in {"unauthorized_or_forbidden", "crm_unavailable", "rate_limited"}:
            return _result(
                records=[],
                source_refs=[],
                errors=[http_status],
                diagnostics=_diagnostics(
                    status="ERROR",
                    reason=http_status,
                    records_returned=0,
                    pages_read=pages_read,
                    max_records=max_records,
                    runtime_enabled=runtime_enabled,
                    transport=transport,
                ),
            )
        if transport_error in {"non_json_response", "empty_response"}:
            return _result(
                records=[],
                source_refs=[],
                errors=["crm_unavailable"],
                diagnostics=_diagnostics(
                    status="ERROR",
                    reason="crm_unavailable",
                    records_returned=0,
                    pages_read=pages_read,
                    max_records=max_records,
                    runtime_enabled=runtime_enabled,
                    transport=transport,
                ),
            )
        errors = response.get("errors")
        if isinstance(errors, list) and errors:
            return _result(
                records=[],
                source_refs=[],
                errors=["graphql_error"],
                diagnostics=_diagnostics(
                    status="ERROR",
                    reason="graphql_error",
                    graphql_errors_count=len(errors),
                    records_returned=0,
                    pages_read=pages_read,
                    max_records=max_records,
                    runtime_enabled=runtime_enabled,
                    transport=transport,
                ),
            )

        page_records = _extract_page_records(response)
        if not page_records:
            break
        for raw_record in page_records:
            if len(records) >= max_records:
                break
            if not _safe_string(raw_record.get("id")):
                return _result(
                    records=[],
                    source_refs=[],
                    errors=["missing_required_fields"],
                    diagnostics=_diagnostics(
                        status="ERROR",
                        reason="missing_required_fields",
                        records_returned=0,
                        pages_read=pages_read,
                        max_records=max_records,
                        runtime_enabled=runtime_enabled,
                        transport=transport,
                    ),
                )
            record, source_ref = _normalize_business_chance(raw_record)
            records.append(record)
            source_refs.append(source_ref)
        if len(records) >= _extract_total(response) or len(records) >= max_records:
            break
        skip += len(page_records)
        limit = min(page_size, max_records - len(records))
    else:
        reached_page_limit = len(records) < _last_total(records, source_refs)

    status = "OK"
    reason = "ok"
    errors = []
    if reached_page_limit:
        status = "INCONCLUSIVE"
        reason = "max_pages_reached"
        errors = ["pagination_limit_reached"]
    elif not records:
        status = "INCONCLUSIVE"
        reason = "empty_result"

    return _result(
        records=records,
        source_refs=source_refs,
        errors=errors,
        diagnostics=_diagnostics(
            status=status,
            reason=reason,
            records_returned=len(records),
            pages_read=pages_read,
            max_records=max_records,
            runtime_enabled=runtime_enabled,
            transport=transport,
        ),
    )


def _read_page(
    request: Mapping[str, Any],
    *,
    transport: BusinessChanceTransport,
    skip: int,
    limit: int,
) -> Mapping[str, Any]:
    window = request["window"]
    scope = request["scope"]
    search = {
        "start": window["start"],
        "end": window["end"],
        "scope_id": scope["scope_id"],
        "owner_ids": list(scope.get("owner_ids", [])),
        "group_ids": list(scope.get("group_ids", [])),
        "skip": skip,
        "limit": limit,
    }
    operation = build_read_operation(OPERATION_NAME, variables={"search": search})
    return transport.execute(operation.operation_name, operation.query, operation.variables)


def _validate_request(request: Mapping[str, Any], *, max_records: int) -> str | None:
    window = request.get("window")
    if not isinstance(window, Mapping) or not window.get("start"):
        return "missing_window_start"
    if not window.get("end"):
        return "missing_window_end"
    if str(window["start"]) > str(window["end"]):
        return "invalid_window"
    scope = request.get("scope")
    if not isinstance(scope, Mapping) or not scope.get("scope_id"):
        return "missing_scope_id"
    if max_records <= 0:
        return "invalid_max_records"
    if max_records > MAX_RECORDS_CAP:
        return "max_records_exceeds_cap"
    return None


def _requested_max_records(request: Mapping[str, Any]) -> int:
    options = request.get("options", {})
    if not isinstance(options, Mapping):
        return DEFAULT_PAGE_SIZE
    value = options.get("max_records", DEFAULT_PAGE_SIZE)
    if not isinstance(value, int):
        return 0
    return value


def _extract_page_records(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    connection = _business_chance_connection(response)
    data = connection.get("data")
    if not isinstance(data, list):
        return []
    return [record for record in data if isinstance(record, Mapping)]


def _extract_total(response: Mapping[str, Any]) -> int:
    connection = _business_chance_connection(response)
    total = connection.get("total", 0)
    return total if isinstance(total, int) else 0


def _business_chance_connection(response: Mapping[str, Any]) -> Mapping[str, Any]:
    data = response.get("data")
    if not isinstance(data, Mapping):
        return {}
    connection = data.get(OPERATION_NAME)
    if not isinstance(connection, Mapping):
        return {}
    return connection


def _normalize_business_chance(raw_record: Mapping[str, Any]) -> tuple[dict[str, object], dict[str, object]]:
    source_id = _safe_string(raw_record.get("id"))
    source_ref_id = f"src-{source_id}"
    record = {
        "id": source_id,
        "project_id": _extract_project_id(raw_record),
        "status": _safe_string(raw_record.get("status")),
        "apply_status": _safe_string(raw_record.get("apply_status")),
        "owner": _extract_owner(raw_record),
        "due_at": _safe_string(raw_record.get("due_at")),
        "created_at": _safe_string(raw_record.get("created_at")),
        "updated_at": _safe_string(raw_record.get("updated_at")),
        "source_ref_ids": [source_ref_id],
    }
    source_ref = {
        "id": source_ref_id,
        "system": "crm-graphql",
        "query": OPERATION_NAME,
        "entity_type": "BusinessChance",
        "source_id": source_id,
        "fields": SOURCE_REF_FIELDS,
    }
    return record, source_ref


def _extract_project_id(raw_record: Mapping[str, Any]) -> str:
    project = raw_record.get("project")
    if isinstance(project, Mapping):
        project_id = _safe_string(project.get("id"))
        if project_id:
            return project_id
    return _safe_string(raw_record.get("project_id"))


def _extract_owner(raw_record: Mapping[str, Any]) -> dict[str, str]:
    claim_by = raw_record.get("claim_by")
    if not isinstance(claim_by, Mapping):
        return {"id": "", "name": ""}
    return {"id": _safe_string(claim_by.get("id")), "name": _safe_string(claim_by.get("name"))}


def _safe_string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _diagnostics(
    *,
    status: str,
    reason: str,
    records_returned: int,
    pages_read: int,
    max_records: int,
    graphql_errors_count: int = 0,
    runtime_enabled: bool = False,
    transport: BusinessChanceTransport | None = None,
    auth_mode: str | None = None,
    endpoint_configured: bool = False,
    token_configured: bool = False,
) -> dict[str, object]:
    return {
        "auth_mode": _auth_mode(transport, auth_mode=auth_mode),
        "endpoint_configured": endpoint_configured,
        "http_status_category": _http_status_category(transport),
        "read_only": True,
        "mutations_allowed": False,
        "mutation_used": False,
        "operation_name": OPERATION_NAME,
        "graphql_errors_count": graphql_errors_count,
        "records_returned": records_returned,
        "pages_read": pages_read,
        "max_records": max_records,
        "pagination_limit_reached": reason == "max_pages_reached",
        "runtime_enabled": runtime_enabled,
        "status": status,
        "status_code_category": _status_code_category(transport),
        "token_configured": token_configured,
        "transport_error_category": _transport_error_category(transport),
        "reason": reason,
    }


def _config_missing_result(
    *,
    max_records: int,
    auth_mode: str,
    runtime_enabled: bool = False,
    endpoint_configured: bool = False,
    token_configured: bool = False,
) -> dict[str, object]:
    return _result(
        records=[],
        source_refs=[],
        errors=["config_missing"],
        diagnostics=_diagnostics(
            status="ERROR",
            reason="config_missing",
            records_returned=0,
            pages_read=0,
            max_records=max_records,
            runtime_enabled=runtime_enabled,
            auth_mode=auth_mode,
            endpoint_configured=endpoint_configured,
            token_configured=token_configured,
        ),
    )


def _auth_mode(transport: BusinessChanceTransport | None, *, auth_mode: str | None) -> str:
    value = getattr(transport, "auth_mode", auth_mode or "mock")
    return value if value in {"mock", "bearer", "private_token", "cookie"} else "mock"


def _http_status_category(transport: BusinessChanceTransport | None) -> str:
    value = getattr(transport, "http_status_category", "not_attempted")
    if value in {"not_attempted", "success", "unauthorized_or_forbidden", "crm_unavailable", "rate_limited"}:
        return value
    return "crm_unavailable"


def _status_code_category(transport: BusinessChanceTransport | None) -> str | None:
    value = getattr(transport, "status_code_category", None)
    if value in {"2xx", "3xx", "4xx", "5xx", "not_available"}:
        return value
    return None


def _transport_error_category(transport: BusinessChanceTransport | None) -> str | None:
    value = getattr(transport, "transport_error_category", None)
    allowed = {
        "dns_error",
        "connect_timeout",
        "read_timeout",
        "connection_refused",
        "connection_reset",
        "tls_error",
        "invalid_url",
        "http_4xx",
        "http_5xx",
        "non_json_response",
        "empty_response",
        "network_unreachable",
        "unknown_transport_error",
    }
    return value if value in allowed else None


def _result(
    *,
    records: list[dict[str, object]],
    source_refs: list[dict[str, object]],
    errors: list[str],
    diagnostics: dict[str, object],
) -> dict[str, object]:
    return {
        "records": records,
        "source_refs": source_refs,
        "errors": sanitize_errors(errors),
        "diagnostics": diagnostics,
    }


def _last_total(records: list[dict[str, object]], source_refs: list[dict[str, object]]) -> int:
    return max(len(records), len(source_refs) + 1)
