from __future__ import annotations

import json
from pathlib import Path

SENSITIVE_MARKERS = (
    "https://crm.example.internal/query",
    "http://api.in.chaitin.net/crm/query",
    "fake-token-123",
    "Authorization",
    "Bearer",
    "cookie",
    "raw GraphQL request",
    "raw GraphQL response",
    "query listProject",
    "variables",
    "Synthetic Project Name",
    "Synthetic Customer Name",
    "20000",
    "amount",
    "contact",
    "phone",
    "email",
    "address",
    "free-text CRM note",
)

SMOKE_ALLOWED_KEYS = {
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

PROJECT_DIAGNOSTIC_ALLOWED_KEYS = {
    "auth_mode",
    "endpoint_configured",
    "status",
    "reason",
    "read_only",
    "mutations_allowed",
    "mutation_used",
    "operation_name",
    "graphql_errors_count",
    "http_status_category",
    "records_returned",
    "pages_read",
    "max_records",
    "pagination_limit_reached",
    "runtime_enabled",
    "status_code_category",
    "token_configured",
    "transport_error_category",
}

WRITE_LIKE_FRAGMENTS = (
    "create",
    "update",
    "delete",
    "remove",
    "assign",
    "claim",
    "transfer",
    "review",
    "audit",
    "sync",
    "send",
    "contact",
    "message",
    "task",
    "export",
    "writeback",
)


class RecordingTransport:
    def __init__(self, responses: list[dict[str, object]]):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []
        self.endpoint = "https://crm.example.internal/query"
        self.token = "fake-token-123"

    def execute(self, operation_name: str, query: str, variables: dict[str, object]):
        self.calls.append({"operation_name": operation_name, "query": query, "variables": variables})
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


def assert_no_sensitive_output(result: object) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized


def valid_project_request(max_records: int = 1) -> dict[str, object]:
    return {
        "window": {"start": "2026-01-01", "end": "2026-01-31"},
        "scope": {"scope_id": "synthetic-team"},
        "options": {"max_records": max_records},
    }


def sensitive_project(project_id: str = "project-1") -> dict[str, object]:
    return {
        "id": project_id,
        "name": "Synthetic Project Name",
        "stage": "proposal",
        "amount": "20000",
        "customer": {"name": "Synthetic Customer Name"},
        "claimBy": {"user": {"id": "owner-1", "name": "Synthetic Owner"}},
        "created_at": "2026-01-02T00:00:00Z",
        "updated_at": "2026-01-03T00:00:00Z",
        "phone": "phone",
        "email": "email",
        "contact": "contact",
        "address": "address",
        "note": "free-text CRM note",
    }


def list_project_response(records: list[dict[str, object]], total: int | None = None):
    return {"data": {"listProject": {"data": records, "total": len(records) if total is None else total}}}


def test_sanitize_graphql_error_does_not_leak_raw_message():
    from crm_mcp_server.redaction import sanitize_error

    result = sanitize_error(
        "graphql_error",
        "raw GraphQL response from https://crm.example.internal/query has Synthetic Customer Name and fake-token-123",
    )

    assert result["category"] == "graphql_error"
    assert result["retryable"] is False
    assert_no_sensitive_output(result)


def test_sanitize_unauthorized_error_does_not_leak_auth_material():
    from crm_mcp_server.redaction import sanitize_error

    result = sanitize_error(
        "unauthorized_or_forbidden",
        "Authorization Bearer fake-token-123 cookie session=abc",
    )

    assert result["category"] == "unauthorized_or_forbidden"
    assert result["retryable"] is False
    assert_no_sensitive_output(result)


def test_unknown_error_category_uses_safe_fallback():
    from crm_mcp_server.redaction import sanitize_error

    result = sanitize_error("raw_internal_exception", "Synthetic Project Name fake-token-123")

    assert result["category"] == "internal_error"
    assert result["retryable"] is False
    assert_no_sensitive_output(result)


def test_smoke_check_all_output_paths_are_sanitized():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check

    results = [
        crm_smoke_check(),
        crm_smoke_check(
            runtime_enabled=True,
            transport=MockGraphQLTransport(response=list_project_response([sensitive_project()])),
        ),
        crm_smoke_check(runtime_enabled=True, transport=MockGraphQLTransport(response=list_project_response([]))),
        crm_smoke_check(
            runtime_enabled=True,
            transport=MockGraphQLTransport(
                response={
                    "errors": [
                        {
                            "message": "raw GraphQL response Synthetic Project Name fake-token-123",
                            "extensions": {"Authorization": "Bearer fake-token-123"},
                        }
                    ]
                }
            ),
        ),
        crm_smoke_check(
            runtime_enabled=True,
            transport=MockGraphQLTransport(
                response={"errors": [{"message": "Authorization Bearer fake-token-123"}]},
                http_status_category="unauthorized_or_forbidden",
            ),
        ),
    ]

    for result in results:
        assert set(result) == SMOKE_ALLOWED_KEYS
        assert result["read_only"] is True
        assert result["mutations_allowed"] is False
        assert result["mutation_used"] is False
        assert_no_sensitive_output(result)


def test_list_projects_all_output_paths_are_sanitized():
    from crm_mcp_server.projects import crm_list_projects

    results = [
        crm_list_projects(
            valid_project_request(),
            transport=RecordingTransport([list_project_response([sensitive_project()])]),
        ),
        crm_list_projects(
            valid_project_request(),
            transport=RecordingTransport([list_project_response([])]),
        ),
        crm_list_projects(
            valid_project_request(),
            transport=RecordingTransport(
                [
                    {
                        "errors": [
                            {
                                "message": "raw GraphQL response Synthetic Project Name fake-token-123",
                                "extensions": {"Authorization": "Bearer fake-token-123"},
                            }
                        ]
                    }
                ]
            ),
        ),
        crm_list_projects(
            {"window": {"start": "2026-02-01", "end": "2026-01-01"}, "scope": {"scope_id": "synthetic-team"}},
            transport=RecordingTransport([list_project_response([sensitive_project()])]),
        ),
        crm_list_projects(
            {**valid_project_request(max_records=10)},
            transport=RecordingTransport(
                [
                    list_project_response([sensitive_project("project-1")], total=10),
                    list_project_response([sensitive_project("project-2")], total=10),
                ]
            ),
            page_size=1,
            max_pages=2,
        ),
        crm_list_projects(
            valid_project_request(),
            transport=RecordingTransport([list_project_response([{**sensitive_project(), "id": ""}])]),
        ),
    ]

    for result in results:
        assert set(result["diagnostics"]) == PROJECT_DIAGNOSTIC_ALLOWED_KEYS
        assert result["diagnostics"]["read_only"] is True
        assert result["diagnostics"]["mutations_allowed"] is False
        assert result["diagnostics"]["mutation_used"] is False
        assert_no_sensitive_output(result)


def test_tool_errors_have_uniform_safe_shape():
    from crm_mcp_server.diagnostics import MockGraphQLTransport, crm_smoke_check
    from crm_mcp_server.projects import crm_list_projects

    results = [
        crm_smoke_check(),
        crm_smoke_check(
            runtime_enabled=True,
            transport=MockGraphQLTransport(response={"errors": [{"message": "fake-token-123"}]}),
        ),
        crm_list_projects(
            {"window": {"start": "2026-02-01", "end": "2026-01-01"}, "scope": {"scope_id": "synthetic-team"}},
            transport=RecordingTransport([list_project_response([sensitive_project()])]),
        ),
        crm_list_projects(
            valid_project_request(),
            transport=RecordingTransport([{"errors": [{"message": "fake-token-123"}]}]),
        ),
    ]

    for result in results:
        for error in result["errors"]:
            assert set(error) == {"category", "message", "retryable"}
            assert isinstance(error["message"], str)
            assert isinstance(error["retryable"], bool)
            assert_no_sensitive_output(error)


def test_exposed_tool_names_still_exclude_write_like_fragments():
    from crm_mcp_server.contract import list_v1_read_only_tools

    for tool_name in list_v1_read_only_tools():
        for fragment in WRITE_LIKE_FRAGMENTS:
            assert fragment not in tool_name


def test_runtime_source_does_not_add_network_or_env_access():
    root = Path("crm_mcp_server/crm_mcp_server")
    texts = {str(path): path.read_text() for path in root.glob("*.py") if path.name != "real_smoke.py"}
    for path, text in texts.items():
        forbidden = [
            "os.environ",
            "dotenv",
            ".env",
            "requests.",
            "httpx.",
            "urllib.request",
            "aiohttp.",
            "Authorization",
            "Bearer ",
        ]
        hits = [item for item in forbidden if item in text]
        assert not hits, (path, hits)
