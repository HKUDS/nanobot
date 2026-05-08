"""Sanitized CRM read-boundary diagnostics with mocked transport only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from crm_mcp_server.contract import list_v1_query_names
from crm_mcp_server.graphql import build_read_operation
from crm_mcp_server.redaction import sanitize_errors

SMOKE_OPERATION_NAME = "listProject"


@dataclass
class MockGraphQLTransport:
    """Synthetic transport for tests; it never opens network connections."""

    response: Mapping[str, Any]
    http_status_category: str = "success"
    endpoint: str | None = None
    token: str | None = None
    calls: list[str] = field(default_factory=list)

    def execute(self, operation_name: str, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(operation_name)
        return self.response


def crm_smoke_check(
    *,
    runtime_enabled: bool = False,
    transport: MockGraphQLTransport | None = None,
) -> dict[str, object]:
    """Return sanitized diagnostics for the future real CRM smoke path."""

    base = _base_result(runtime_enabled=runtime_enabled)
    if not runtime_enabled or transport is None:
        return _finish(base, status="INCONCLUSIVE", reason="config_missing", errors=["config_missing"])

    operation = build_read_operation(
        SMOKE_OPERATION_NAME,
        variables={"search": {"skip": 0, "limit": 1}},
    )
    response = transport.execute(operation.operation_name, operation.query, operation.variables)
    base["http_status_category"] = _safe_http_status_category(transport.http_status_category)

    errors = response.get("errors", ())
    graphql_errors_count = len(errors) if isinstance(errors, list) else 0
    base["graphql_errors_count"] = graphql_errors_count
    if base["http_status_category"] == "unauthorized_or_forbidden":
        return _finish(base, status="ERROR", reason="unauthorized_or_forbidden", errors=["unauthorized_or_forbidden"])
    if graphql_errors_count:
        return _finish(base, status="ERROR", reason="graphql_error", errors=["graphql_error"])

    data_count = _count_response_records(response)
    base["data_count"] = data_count
    base["normalized_count"] = data_count
    if data_count == 0:
        return _finish(base, status="INCONCLUSIVE", reason="empty_result", errors=[])
    return _finish(base, status="OK", reason="ok", errors=[])


def _base_result(*, runtime_enabled: bool) -> dict[str, object]:
    return {
        "status": "INCONCLUSIVE",
        "read_only": True,
        "mutations_allowed": False,
        "runtime_enabled": runtime_enabled,
        "allowed_operations": list(list_v1_query_names()),
        "operation_name": SMOKE_OPERATION_NAME,
        "mutation_used": False,
        "http_status_category": "not_attempted",
        "graphql_errors_count": 0,
        "data_count": 0,
        "normalized_count": 0,
        "reason": "config_missing",
        "errors": [],
    }


def _finish(
    result: dict[str, object],
    *,
    status: str,
    reason: str,
    errors: list[str],
) -> dict[str, object]:
    result["status"] = status
    result["reason"] = reason
    result["errors"] = sanitize_errors(errors)
    result["mutation_used"] = False
    result["mutations_allowed"] = False
    result["read_only"] = True
    return result


def _safe_http_status_category(category: str) -> str:
    allowed = {"success", "not_attempted", "unauthorized_or_forbidden", "crm_unavailable", "rate_limited"}
    if category in allowed:
        return category
    return "crm_unavailable"


def _count_response_records(response: Mapping[str, Any]) -> int:
    data = response.get("data")
    if not isinstance(data, Mapping):
        return 0
    operation_data = data.get(SMOKE_OPERATION_NAME)
    if not isinstance(operation_data, Mapping):
        return 0
    records = operation_data.get("data")
    if isinstance(records, list):
        return len(records)
    if operation_data:
        return 1
    return 0
