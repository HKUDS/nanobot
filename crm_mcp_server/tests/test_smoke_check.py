from __future__ import annotations

import json

SENSITIVE_MARKERS = (
    "https://crm.example.internal/query",
    "fake-token-123",
    "Authorization",
    "Bearer",
    "raw GraphQL request",
    "raw GraphQL response",
    "Synthetic Customer Name",
    "Synthetic Project Name",
    "20000",
    "contact",
    "phone",
    "email",
    "free-text CRM note",
)

ALLOWED_KEYS = {
    "status",
    "read_only",
    "mutations_allowed",
    "runtime_enabled",
    "allowed_operations",
    "operation_name",
    "mutation_used",
    "http_status_category",
    "graphql_errors_count",
    "data_count",
    "normalized_count",
    "reason",
    "errors",
    "transport_attempted",
    "response_json_parsed",
    "data_root_present",
    "operation_data_present",
    "records_field_present",
    "records_is_list",
    "reported_total",
    "transport_error_category",
    "status_code_category",
    "endpoint_configured",
    "token_configured",
    "proxy_configured",
    "graphql_error_category",
    "graphql_error_path_present",
    "graphql_error_extensions_present",
    "auth_mode",
    "auth_error_category",
}


def expected_error(category: str, message: str) -> dict[str, object]:
    return {"category": category, "message": message, "retryable": False}


def test_crm_smoke_check_is_legacy_helper_not_live_stdio_tool():
    from crm_mcp_server.contract import list_v1_read_only_tools, list_v1_tools

    assert "crm_smoke_check" not in list_v1_tools()
    assert "crm_smoke_check" not in list_v1_read_only_tools()


def test_default_disabled_config_returns_config_missing():
    from crm_mcp_server.diagnostics import crm_smoke_check

    result = crm_smoke_check()

    assert set(result) == ALLOWED_KEYS
    assert result["status"] == "INCONCLUSIVE"
    assert result["read_only"] is True
    assert result["mutations_allowed"] is False
    assert result["runtime_enabled"] is False
    assert result["mutation_used"] is False
    assert result["reason"] == "config_missing"
    assert result["errors"] == [
        expected_error("config_missing", "Required runtime configuration is missing.")
    ]


def test_mocked_successful_empty_result_returns_empty_result():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(response={"data": {"listProject": {"data": [], "total": 0}}})

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "INCONCLUSIVE"
    assert result["reason"] == "empty_result"
    assert result["http_status_category"] == "success"
    assert result["transport_attempted"] is True
    assert result["response_json_parsed"] is True
    assert result["data_root_present"] is True
    assert result["operation_data_present"] is True
    assert result["records_field_present"] is True
    assert result["records_is_list"] is True
    assert result["reported_total"] == 0
    assert result["graphql_errors_count"] == 0
    assert result["data_count"] == 0
    assert result["normalized_count"] == 0
    assert result["mutation_used"] is False
    assert transport.calls == ["listProject"]


def test_crm_unavailable_does_not_report_empty_result():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(response={}, http_status_category="crm_unavailable")

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "crm_unavailable"
    assert result["http_status_category"] == "crm_unavailable"
    assert result["transport_attempted"] is True
    assert result["response_json_parsed"] is True
    assert result["data_root_present"] is False


def test_empty_list_uses_success_http_category_and_empty_result_reason():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(response={"data": {"listProject": {"data": []}}})

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "INCONCLUSIVE"
    assert result["reason"] == "empty_result"
    assert result["http_status_category"] == "success"


def test_operation_data_missing_returns_operation_data_missing():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(response={"data": {}})

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "operation_data_missing"
    assert result["data_root_present"] is True
    assert result["operation_data_present"] is False
    assert result["records_field_present"] is False


def test_records_field_missing_returns_records_field_missing():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(response={"data": {"listProject": {"total": 0}}})

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "records_field_missing"
    assert result["data_root_present"] is True
    assert result["operation_data_present"] is True
    assert result["records_field_present"] is False
    assert result["reported_total"] == 0


def test_invalid_response_when_data_root_missing():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(response={})

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "invalid_response"
    assert result["data_root_present"] is False



def test_raw_response_with_sensitive_content_does_not_leak():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(
        response={
            "data": {
                "listProject": {
                    "data": [
                        {
                            "token": "fake-token-123",
                            "project": "Synthetic Project Name",
                            "customer": "Synthetic Customer Name",
                            "name": "Synthetic Customer Name",
                            "amount": "20000",
                            "contact": "contact",
                            "note": "free-text CRM note",
                        }
                    ],
                    "total": 1,
                }
            }
        }
    )

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "OK"
    assert_no_sensitive_output(result)


def test_mocked_one_record_path_returns_sanitized_counts():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(
        response={
            "data": {
                "listProject": {
                    "data": [
                        {
                            "id": "synthetic-project-1",
                            "name": "Synthetic Project Name",
                            "amount": "20000",
                            "customer": {"name": "Synthetic Customer Name"},
                        }
                    ],
                    "total": 1,
                }
            }
        }
    )

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "OK"
    assert result["reason"] == "ok"
    assert result["data_count"] == 1
    assert result["normalized_count"] == 1
    assert result["errors"] == []
    assert_no_sensitive_output(result)


def test_graphql_error_is_sanitized():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(
        response={
            "errors": [
                {
                    "message": "raw GraphQL response contains Synthetic Customer Name",
                    "extensions": {"token": "fake-token-123"},
                }
            ]
        }
    )

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "graphql_error"
    assert result["graphql_errors_count"] == 1
    assert result["errors"] == [expected_error("graphql_error", "The CRM query returned an error.")]
    assert_no_sensitive_output(result)


def test_unauthorized_is_sanitized():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(
        response={"errors": [{"message": "Authorization Bearer fake-token-123 unauthorized"}]},
        http_status_category="unauthorized_or_forbidden",
    )

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "unauthorized_or_forbidden"
    assert result["http_status_category"] == "unauthorized_or_forbidden"
    assert result["errors"] == [
        expected_error("unauthorized_or_forbidden", "CRM access is unauthorized or forbidden.")
    ]
    assert result["mutation_used"] is False
    assert_no_sensitive_output(result)


def test_forbidden_sensitive_strings_do_not_appear_in_any_output_path():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    transport = MockGraphQLTransport(
        response={
            "data": {
                "listProject": {
                    "data": [
                        {
                            "id": "synthetic-project-1",
                            "name": "Synthetic Project Name",
                            "note": "free-text CRM note",
                            "phone": "phone",
                            "email": "email",
                            "contact": "contact",
                        }
                    ],
                    "total": 1,
                }
            }
        },
        endpoint="https://crm.example.internal/query",
        token="fake-token-123",
    )

    result = crm_smoke_check(runtime_enabled=True, transport=transport)

    assert result["mutation_used"] is False
    assert_no_sensitive_output(result)


def assert_no_sensitive_output(result: dict[str, object]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized
