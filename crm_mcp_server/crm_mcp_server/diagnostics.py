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
    endpoint_configured: bool = False,
    token_configured: bool = False,
    proxy_configured: bool = False,
    auth_mode: str = "bearer",
) -> dict[str, object]:
    """Return sanitized diagnostics for the future real CRM smoke path."""

    base = _base_result(runtime_enabled=runtime_enabled)
    base["endpoint_configured"] = endpoint_configured
    base["token_configured"] = token_configured
    base["proxy_configured"] = proxy_configured
    base["auth_mode"] = _safe_auth_mode(auth_mode)
    if not runtime_enabled or transport is None:
        return _finish(base, status="INCONCLUSIVE", reason="config_missing", errors=["config_missing"])

    operation = build_read_operation(
        SMOKE_OPERATION_NAME,
        variables={
            "search": {},
            "pagination": {"skip": 0, "limit": 1},
            "sort_by": {"by": "updatedAt", "order": -1},
        },
    )
    response = transport.execute(operation.operation_name, operation.query, operation.variables)
    base["transport_attempted"] = True
    base["transport_error_category"] = _safe_transport_error_category(
        getattr(transport, "transport_error_category", None)
    )
    base["response_json_parsed"] = bool(getattr(transport, "response_json_parsed", isinstance(response, Mapping)))
    base["http_status_category"] = _safe_http_status_category(transport.http_status_category)
    base["status_code_category"] = _safe_status_code_category(getattr(transport, "status_code_category", None))

    errors = response.get("errors", ())
    graphql_errors_count = len(errors) if isinstance(errors, list) else 0
    base["graphql_errors_count"] = graphql_errors_count
    if base["http_status_category"] == "unauthorized_or_forbidden":
        base["auth_error_category"] = "transport_auth_rejected"
        return _finish(base, status="ERROR", reason="unauthorized_or_forbidden", errors=["unauthorized_or_forbidden"])
    if base["http_status_category"] == "rate_limited":
        return _finish(base, status="ERROR", reason="rate_limited", errors=["rate_limited"])
    if base["http_status_category"] == "crm_unavailable":
        return _finish(base, status="ERROR", reason="crm_unavailable", errors=["crm_unavailable"])
    if base["transport_error_category"] in {"non_json_response", "empty_response"}:
        return _finish(base, status="ERROR", reason="crm_unavailable", errors=["crm_unavailable"])
    if graphql_errors_count:
        base.update(_inspect_graphql_errors(errors))
        return _finish(base, status="ERROR", reason="graphql_error", errors=["graphql_error"])

    response_shape = _inspect_response_shape(response)
    base.update(response_shape.diagnostics)
    if response_shape.reason is not None:
        return _finish(base, status="ERROR", reason=response_shape.reason, errors=[response_shape.reason])
    base["data_count"] = response_shape.data_count
    base["normalized_count"] = response_shape.data_count
    if response_shape.data_count == 0:
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
        "transport_attempted": False,
        "transport_error_category": None,
        "response_json_parsed": False,
        "status_code_category": None,
        "endpoint_configured": False,
        "token_configured": False,
        "proxy_configured": False,
        "auth_mode": "bearer",
        "auth_error_category": None,
        "data_root_present": False,
        "operation_data_present": False,
        "records_field_present": False,
        "records_is_list": False,
        "reported_total": None,
        "graphql_errors_count": 0,
        "graphql_error_category": None,
        "graphql_error_path_present": False,
        "graphql_error_extensions_present": False,
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


def _safe_status_code_category(category: object) -> str | None:
    if category in {"2xx", "3xx", "4xx", "5xx", "not_available"}:
        return str(category)
    return None


def _safe_transport_error_category(category: object) -> str | None:
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
    if category in allowed:
        return str(category)
    return None


def _safe_auth_mode(auth_mode: object) -> str:
    if auth_mode in {"private_token", "bearer", "cookie"}:
        return str(auth_mode)
    return "bearer"


def _inspect_graphql_errors(errors: object) -> dict[str, object]:
    if not isinstance(errors, list):
        return {
            "graphql_error_category": "graphql_unknown_error",
            "graphql_error_path_present": False,
            "graphql_error_extensions_present": False,
        }
    path_present = any(isinstance(error, Mapping) and "path" in error for error in errors)
    extensions_present = any(isinstance(error, Mapping) and "extensions" in error for error in errors)
    return {
        "graphql_error_category": _classify_graphql_error(errors),
        "auth_error_category": _classify_auth_error(errors),
        "graphql_error_path_present": path_present,
        "graphql_error_extensions_present": extensions_present,
    }


def _classify_graphql_error(errors: list[object]) -> str:
    saw_validation = False
    for error in errors:
        if not isinstance(error, Mapping):
            continue
        code = _safe_lower(error.get("extensions", {}).get("code") if isinstance(error.get("extensions"), Mapping) else None)
        message = _safe_lower(error.get("message"))
        if any(fragment in code for fragment in ("forbidden", "unauthorized", "permission", "auth")):
            return "graphql_auth_scope_error"
        if any(fragment in code for fragment in ("internal", "resolver", "execution", "exception")):
            return "graphql_execution_error"
        if any(fragment in code for fragment in ("variable", "coerc")):
            return "graphql_variable_error"
        if any(fragment in code for fragment in ("validation", "parse", "syntax")):
            saw_validation = True
        if any(fragment in message for fragment in ("forbidden", "unauthorized", "permission", "not login")):
            return "graphql_auth_scope_error"
        if any(fragment in message for fragment in ("variable", "coerc", "required type", "was not provided", "invalid value")):
            return "graphql_variable_error"
        if any(fragment in message for fragment in ("cannot query field", "unknown field")):
            return "graphql_unknown_field"
        if any(fragment in message for fragment in ("internal", "resolver", "execution", "exception")):
            return "graphql_execution_error"
        if any(fragment in message for fragment in ("validation", "parse", "syntax")):
            saw_validation = True
    if saw_validation:
        return "graphql_validation_error"
    return "graphql_unknown_error"


def _classify_auth_error(errors: list[object]) -> str | None:
    for error in errors:
        if not isinstance(error, Mapping):
            continue
        message = _safe_lower(error.get("message"))
        code = _safe_lower(error.get("extensions", {}).get("code") if isinstance(error.get("extensions"), Mapping) else None)
        combined = f"{code} {message}"
        if "not login" in combined:
            return "not_login"
        if any(fragment in combined for fragment in ("forbidden", "unauthorized", "permission")):
            return "graphql_auth_rejected"
    return None


def _safe_lower(value: object) -> str:
    return str(value).lower() if isinstance(value, str) else ""


@dataclass(frozen=True)
class ResponseShape:
    diagnostics: dict[str, object]
    data_count: int
    reason: str | None = None


def _inspect_response_shape(response: Mapping[str, Any]) -> ResponseShape:
    diagnostics: dict[str, object] = {
        "data_root_present": False,
        "operation_data_present": False,
        "records_field_present": False,
        "records_is_list": False,
        "reported_total": None,
    }
    data = response.get("data")
    if not isinstance(data, Mapping):
        return ResponseShape(diagnostics=diagnostics, data_count=0, reason="invalid_response")
    diagnostics["data_root_present"] = True
    operation_data = data.get(SMOKE_OPERATION_NAME)
    if not isinstance(operation_data, Mapping):
        return ResponseShape(diagnostics=diagnostics, data_count=0, reason="operation_data_missing")
    diagnostics["operation_data_present"] = True
    reported_total = operation_data.get("total")
    diagnostics["reported_total"] = reported_total if isinstance(reported_total, int) else None
    if "data" not in operation_data:
        return ResponseShape(diagnostics=diagnostics, data_count=0, reason="records_field_missing")
    diagnostics["records_field_present"] = True
    records = operation_data.get("data")
    if isinstance(records, list):
        diagnostics["records_is_list"] = True
        return ResponseShape(diagnostics=diagnostics, data_count=len(records))
    return ResponseShape(diagnostics=diagnostics, data_count=0, reason="records_field_missing")
