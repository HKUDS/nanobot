"""Sanitized diagnostics for optional read-only CRM smoke checks."""

from __future__ import annotations

from datetime import date

from nanobot.crm.graphql_client import CRMGraphQLClient, GraphQLTransport
from nanobot.crm.models import ReportRequest, ReportScope, ReportType, ReportWindow
from nanobot.crm.real_adapter import _PROJECT_QUERY, RealCRMAdapter

_OPERATION_NAME = "listProject"
_LIMIT = 1
_PROJECT_FIELDS = (
    "id",
    "name",
    "updated_at",
    "created_at",
    "stage",
    "claimBy",
    "company",
    "amount",
    "actual_amount",
)


def run_list_project_diagnostics(
    *,
    endpoint: str | None,
    token: str | None,
    transport: GraphQLTransport,
) -> dict[str, object]:
    """Run a limit-1 `listProject` diagnostic without exposing payload values."""

    diagnostics = _base_diagnostics(endpoint_present=bool(endpoint), token_present=bool(token))
    if not endpoint or not token:
        diagnostics["root_cause_category"] = "config_missing"
        return diagnostics

    client = CRMGraphQLClient(endpoint=endpoint, token=token, transport=transport)
    adapter = RealCRMAdapter(client=client, page_limit=_LIMIT)
    request = ReportRequest(
        report_type=ReportType.DASHBOARD,
        window=ReportWindow(start=date(1970, 1, 1), end=date.today()),
        scope=ReportScope(scope_id="real-smoke-readonly"),
    )
    variables = {
        "search": adapter._project_search(request),
        "sortBy": {"by": "updatedAt", "order": -1},
        "pagination": {"skip": 0, "limit": _LIMIT},
    }

    if CRMGraphQLClient._contains_mutation(_PROJECT_QUERY):
        diagnostics["mutation_used"] = True
        diagnostics["root_cause_category"] = "unknown"
        return diagnostics

    try:
        response = transport(
            endpoint=endpoint,
            token=token,
            operation_name=_OPERATION_NAME,
            query=_PROJECT_QUERY,
            variables=variables,
        )
    except Exception:
        diagnostics["http_reached"] = False
        diagnostics["http_status_category"] = "network_error"
        diagnostics["root_cause_category"] = "network_unreachable"
        return diagnostics

    diagnostics["http_reached"] = True
    diagnostics["http_status_category"] = _status_category(response)

    errors = response.get("errors") if isinstance(response, dict) else None
    error_messages = CRMGraphQLClient._format_errors(errors)
    diagnostics["graphql_errors_count"] = len(error_messages) if errors else 0
    diagnostics["graphql_error_categories"] = tuple(_categorize_graphql_error(message) for message in error_messages)
    if errors:
        diagnostics["root_cause_category"] = _root_cause_for_graphql_errors(error_messages)
        return diagnostics

    data = response.get("data") if isinstance(response, dict) else None
    diagnostics["top_level_field_present"] = isinstance(data, dict) and _OPERATION_NAME in data
    connection = data.get(_OPERATION_NAME) if isinstance(data, dict) else None
    diagnostics["connection_present"] = isinstance(connection, dict)
    diagnostics["connection_total_present"] = isinstance(connection, dict) and "total" in connection
    records = connection.get("data") if isinstance(connection, dict) else None
    data_count = min(len(records), 1) if isinstance(records, list) else 0
    diagnostics["data_count"] = data_count

    first_record = records[0] if isinstance(records, list) and records and isinstance(records[0], dict) else None
    diagnostics["first_record_field_presence"] = {
        field: isinstance(first_record, dict) and field in first_record for field in _PROJECT_FIELDS
    }

    if not isinstance(connection, dict):
        diagnostics["root_cause_category"] = "graphql_error" if data is None else "unknown"
        return diagnostics
    if not isinstance(records, list):
        diagnostics["root_cause_category"] = "graphql_error"
        return diagnostics
    if not records:
        diagnostics["root_cause_category"] = "empty_connection"
        return diagnostics

    try:
        normalized = adapter._normalize_project(records[0])
    except KeyError as exc:
        diagnostics["normalization_error_category"] = f"missing_required_field:{exc.args[0]}"
        diagnostics["root_cause_category"] = "missing_required_field"
        return diagnostics
    except (TypeError, ValueError):
        diagnostics["normalization_error_category"] = "invalid_field_shape"
        diagnostics["root_cause_category"] = "normalization_error"
        return diagnostics

    diagnostics["normalized_count"] = 1 if normalized else 0
    diagnostics["root_cause_category"] = "none"
    return diagnostics


def _base_diagnostics(*, endpoint_present: bool, token_present: bool) -> dict[str, object]:
    return {
        "endpoint_present": endpoint_present,
        "token_present": token_present,
        "operation_name": _OPERATION_NAME,
        "mutation_used": False,
        "limit": _LIMIT,
        "http_reached": False,
        "http_status_category": "not_attempted",
        "graphql_errors_count": 0,
        "graphql_error_categories": (),
        "top_level_field_present": False,
        "connection_present": False,
        "connection_total_present": False,
        "data_count": 0,
        "first_record_field_presence": {field: False for field in _PROJECT_FIELDS},
        "normalized_count": 0,
        "normalization_error_category": None,
        "root_cause_category": "unknown",
    }


def _status_category(response: dict[str, object]) -> str:
    status = response.get("_http_status")
    if isinstance(status, int):
        if 200 <= status < 300:
            return "2xx"
        if 400 <= status < 500:
            return "4xx"
        if 500 <= status < 600:
            return "5xx"
    return "2xx"


def _categorize_graphql_error(message: str) -> str:
    lowered = message.lower()
    if "unauthorized" in lowered or "forbidden" in lowered or "permission" in lowered:
        return "authorization"
    if "validation" in lowered or "cannot query" in lowered or "unknown" in lowered:
        return "schema_or_validation"
    return "graphql_error"


def _root_cause_for_graphql_errors(messages: tuple[str, ...]) -> str:
    categories = {_categorize_graphql_error(message) for message in messages}
    if "authorization" in categories:
        return "unauthorized_or_forbidden"
    return "graphql_error"
