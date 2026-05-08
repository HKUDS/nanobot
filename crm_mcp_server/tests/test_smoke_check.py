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
}


def expected_error(category: str, message: str) -> dict[str, object]:
    return {"category": category, "message": message, "retryable": False}


def test_crm_smoke_check_tool_name_is_exposed_as_read_only():
    from crm_mcp_server.contract import list_v1_tools
    from crm_mcp_server.server import get_server_metadata

    assert "crm_smoke_check" in list_v1_tools()
    smoke_tool = next(tool for tool in get_server_metadata()["tools"] if tool["name"] == "crm_smoke_check")
    assert smoke_tool["read_only"] is True


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
    assert result["graphql_errors_count"] == 0
    assert result["data_count"] == 0
    assert result["normalized_count"] == 0
    assert result["mutation_used"] is False
    assert transport.calls == ["listProject"]


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
