from __future__ import annotations

import json

import pytest

SENSITIVE_MARKERS = (
    "raw GraphQL request",
    "raw GraphQL response",
    "https://crm.example.internal/query",
    "fake-token-123",
    "Authorization",
    "Bearer",
    "cookie",
    "Synthetic Project Name",
    "Synthetic Customer Name",
    "amount",
    "phone",
    "email",
    "contact",
    "address",
    "free-text CRM note",
)

ALLOWED_RECORD_KEYS = {"id", "stage", "owner", "created_at", "updated_at", "source_ref_ids"}
ALLOWED_OWNER_KEYS = {"id", "name"}
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


class RecordingTransport:
    def __init__(self, responses: list[dict[str, object]]):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def execute(self, operation_name: str, query: str, variables: dict[str, object]):
        self.calls.append({"operation_name": operation_name, "variables": variables})
        if not self.responses:
            raise AssertionError("unexpected extra transport call")
        return self.responses.pop(0)


def explode_config_load(*args: object, **kwargs: object) -> object:
    raise AssertionError("unexpected real config load")


def valid_request(max_records: int = 50) -> dict[str, object]:
    return {
        "window": {"start": "2026-01-01", "end": "2026-01-31"},
        "scope": {
            "scope_id": "synthetic-team",
            "owner_ids": ["owner-1"],
            "group_ids": ["group-1"],
        },
        "options": {"max_records": max_records},
    }


def project_record(project_id: str, owner_id: str = "owner-1") -> dict[str, object]:
    return {
        "id": project_id,
        "name": "Synthetic Project Name",
        "stage": "proposal",
        "amount": "20000",
        "customer": {"name": "Synthetic Customer Name"},
        "claimBy": {"id": owner_id, "user": {"name": "Synthetic Owner"}},
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


def expected_error(category: str, message: str) -> dict[str, object]:
    return {"category": category, "message": message, "retryable": False}


def test_crm_list_projects_tool_name_is_exposed_as_read_only():
    from crm_mcp_server.contract import list_v1_tools
    from crm_mcp_server.server import get_server_metadata

    assert "crm_list_projects" in list_v1_tools()
    tool = next(tool for tool in get_server_metadata()["tools"] if tool["name"] == "crm_list_projects")
    assert tool["read_only"] is True


def test_mocked_list_project_response_returns_sanitized_records_and_source_refs():
    from crm_mcp_server.projects import crm_list_projects

    transport = RecordingTransport([list_project_response([project_record("project-1")])])

    result = crm_list_projects(valid_request(max_records=1), transport=transport)

    assert result["errors"] == []
    assert result["diagnostics"] == {
        "auth_mode": "mock",
        "endpoint_configured": False,
        "http_status_category": "not_attempted",
        "read_only": True,
        "mutations_allowed": False,
        "mutation_used": False,
        "operation_name": "listProject",
        "graphql_errors_count": 0,
        "records_returned": 1,
        "pages_read": 1,
        "max_records": 1,
        "pagination_limit_reached": False,
        "runtime_enabled": False,
        "status": "OK",
        "status_code_category": None,
        "token_configured": False,
        "transport_error_category": None,
        "reason": "ok",
    }
    assert result["records"] == [
        {
            "id": "project-1",
            "stage": "proposal",
            "owner": {"id": "owner-1", "name": "Synthetic Owner"},
            "created_at": "2026-01-02T00:00:00Z",
            "updated_at": "2026-01-03T00:00:00Z",
            "source_ref_ids": ["src-project-1"],
        }
    ]
    assert result["source_refs"] == [
        {
            "id": "src-project-1",
            "system": "crm-graphql",
            "query": "listProject",
            "entity_type": "Project",
            "source_id": "project-1",
            "fields": ["id", "stage", "owner.id", "owner.name", "created_at", "updated_at"],
        }
    ]
    assert set(result["records"][0]) == ALLOWED_RECORD_KEYS
    assert set(result["records"][0]["owner"]) == ALLOWED_OWNER_KEYS
    assert_no_sensitive_output(result)


def test_default_without_transport_does_not_access_real_runtime(monkeypatch: pytest.MonkeyPatch):
    from crm_mcp_server import projects

    monkeypatch.setattr(projects, "load_real_smoke_config_from_env", explode_config_load, raising=False)

    result = projects.crm_list_projects(valid_request(max_records=1))

    assert result["records"] == []
    assert result["source_refs"] == []
    assert result["errors"] == [expected_error("config_missing", "Required runtime configuration is missing.")]
    assert result["diagnostics"]["runtime_enabled"] is False
    assert result["diagnostics"]["reason"] == "config_missing"
    assert result["diagnostics"]["mutation_used"] is False
    assert_no_sensitive_output(result)


def test_runtime_disabled_does_not_read_env(monkeypatch: pytest.MonkeyPatch):
    from crm_mcp_server import projects

    monkeypatch.setattr(projects, "load_real_smoke_config_from_env", explode_config_load, raising=False)
    transport = RecordingTransport([list_project_response([project_record("project-1")])])

    result = projects.crm_list_projects(valid_request(max_records=1), transport=transport, runtime_enabled=False)

    assert result["diagnostics"]["runtime_enabled"] is False
    assert transport.calls
    assert_no_sensitive_output(result)


def test_runtime_enabled_missing_env_returns_sanitized_config_missing(monkeypatch: pytest.MonkeyPatch):
    from crm_mcp_server.projects import crm_list_projects

    monkeypatch.delenv("CRM_GRAPHQL_ENDPOINT", raising=False)
    monkeypatch.delenv("CRM_GRAPHQL_TOKEN", raising=False)

    result = crm_list_projects(valid_request(max_records=1), runtime_enabled=True)

    assert result["records"] == []
    assert result["source_refs"] == []
    assert result["errors"] == [expected_error("config_missing", "Required runtime configuration is missing.")]
    assert result["diagnostics"]["runtime_enabled"] is False
    assert result["diagnostics"]["auth_mode"] == "bearer"
    assert result["diagnostics"]["endpoint_configured"] is False
    assert result["diagnostics"]["token_configured"] is False
    assert result["diagnostics"]["reason"] == "config_missing"
    assert_no_sensitive_output(result)


def test_runtime_enabled_builds_bearer_real_transport(monkeypatch: pytest.MonkeyPatch):
    from crm_mcp_server import projects

    seen_configs: list[object] = []

    class FakeRealTransport(RecordingTransport):
        auth_mode = "bearer"
        http_status_category = "success"
        status_code_category = "2xx"
        transport_error_category = None

        def __init__(self, config: object) -> None:
            seen_configs.append(config)
            super().__init__([list_project_response([project_record("project-1")])])

    monkeypatch.setenv("CRM_GRAPHQL_ENDPOINT", "https://crm.example.internal/query")
    monkeypatch.setenv("CRM_GRAPHQL_TOKEN", "fake-token-123")
    monkeypatch.setattr(projects, "RealGraphQLSmokeTransport", FakeRealTransport)

    result = projects.crm_list_projects(valid_request(max_records=1), runtime_enabled=True)

    assert len(seen_configs) == 1
    assert seen_configs[0].auth_mode == "bearer"
    assert result["diagnostics"]["runtime_enabled"] is True
    assert result["diagnostics"]["auth_mode"] == "bearer"
    assert result["diagnostics"]["http_status_category"] == "success"
    assert result["diagnostics"]["status_code_category"] == "2xx"
    assert result["diagnostics"]["mutation_used"] is False
    assert_no_sensitive_output(result)


def test_runtime_enabled_fake_response_stays_sanitized():
    from crm_mcp_server.projects import crm_list_projects

    transport = RecordingTransport([list_project_response([project_record("project-1")])])

    transport.http_status_category = "success"
    transport.status_code_category = "2xx"
    transport.transport_error_category = None
    transport.auth_mode = "bearer"

    result = crm_list_projects(valid_request(max_records=1), transport=transport, runtime_enabled=True)

    assert result["records"] == [
        {
            "id": "project-1",
            "stage": "proposal",
            "owner": {"id": "owner-1", "name": "Synthetic Owner"},
            "created_at": "2026-01-02T00:00:00Z",
            "updated_at": "2026-01-03T00:00:00Z",
            "source_ref_ids": ["src-project-1"],
        }
    ]
    assert set(result["records"][0]) == ALLOWED_RECORD_KEYS
    assert result["diagnostics"]["runtime_enabled"] is True
    assert result["diagnostics"]["auth_mode"] == "bearer"
    assert_no_sensitive_output(result)


@pytest.mark.parametrize(
    ("http_status_category", "expected_error_category", "expected_reason"),
    [
        ("unauthorized_or_forbidden", "unauthorized_or_forbidden", "unauthorized_or_forbidden"),
        ("crm_unavailable", "crm_unavailable", "crm_unavailable"),
        ("rate_limited", "rate_limited", "rate_limited"),
    ],
)
def test_runtime_enabled_transport_errors_are_sanitized(
    http_status_category: str,
    expected_error_category: str,
    expected_reason: str,
):
    from crm_mcp_server.projects import crm_list_projects

    transport = RecordingTransport([{}])
    transport.http_status_category = http_status_category
    transport.status_code_category = "4xx"
    transport.transport_error_category = "http_4xx"
    transport.auth_mode = "bearer"

    result = crm_list_projects(valid_request(max_records=1), transport=transport, runtime_enabled=True)

    assert result["records"] == []
    assert result["source_refs"] == []
    assert result["errors"][0]["category"] == expected_error_category
    assert isinstance(result["errors"][0]["message"], str)
    assert isinstance(result["errors"][0]["retryable"], bool)
    assert result["diagnostics"]["status"] == "ERROR"
    assert result["diagnostics"]["reason"] == expected_reason
    assert result["diagnostics"]["http_status_category"] == http_status_category
    assert result["diagnostics"]["transport_error_category"] == "http_4xx"
    assert_no_sensitive_output(result)


@pytest.mark.parametrize(
    ("request_patch", "reason"),
    [
        ({"window": {"end": "2026-01-31"}}, "missing_window_start"),
        ({"window": {"start": "2026-01-01"}}, "missing_window_end"),
        ({"window": {"start": "2026-02-01", "end": "2026-01-01"}}, "invalid_window"),
        ({"scope": {"owner_ids": ["owner-1"]}}, "missing_scope_id"),
        ({"options": {"max_records": 0}}, "invalid_max_records"),
        ({"options": {"max_records": 201}}, "max_records_exceeds_cap"),
    ],
)
def test_validation_happens_before_transport(request_patch: dict[str, object], reason: str):
    from crm_mcp_server.projects import crm_list_projects

    request = valid_request()
    request.update(request_patch)
    transport = RecordingTransport([list_project_response([project_record("project-1")])])

    result = crm_list_projects(request, transport=transport)

    assert transport.calls == []
    assert result["records"] == []
    assert result["source_refs"] == []
    assert result["errors"] == [expected_error("invalid_request", "The request is invalid.")]
    assert result["diagnostics"]["status"] == "ERROR"
    assert result["diagnostics"]["reason"] == reason
    assert result["diagnostics"]["mutation_used"] is False
    assert set(result["diagnostics"]) == PROJECT_DIAGNOSTIC_ALLOWED_KEYS


def test_pagination_uses_template_pagination_param():
    from crm_mcp_server.projects import crm_list_projects

    transport = RecordingTransport(
        [
            list_project_response([project_record("project-1")], total=2),
            list_project_response([project_record("project-2")], total=2),
        ]
    )

    result = crm_list_projects(valid_request(max_records=2), transport=transport, page_size=1)

    assert [call["operation_name"] for call in transport.calls] == ["listProject", "listProject"]
    assert [call["variables"]["pagination"]["skip"] for call in transport.calls] == [0, 1]
    assert [call["variables"]["pagination"]["limit"] for call in transport.calls] == [1, 1]
    assert [call["variables"]["sort_by"] for call in transport.calls] == [
        {"by": "updatedAt", "order": -1},
        {"by": "updatedAt", "order": -1},
    ]
    assert all("skip" not in call["variables"]["search"] for call in transport.calls)
    assert all("limit" not in call["variables"]["search"] for call in transport.calls)
    assert result["diagnostics"]["pages_read"] == 2
    assert result["diagnostics"]["records_returned"] == 2


def test_max_records_and_max_pages_stop_pagination_safely():
    from crm_mcp_server.projects import crm_list_projects

    transport = RecordingTransport(
        [
            list_project_response([project_record("project-1")], total=10),
            list_project_response([project_record("project-2")], total=10),
        ]
    )

    result = crm_list_projects(valid_request(max_records=10), transport=transport, page_size=1, max_pages=2)

    assert len(transport.calls) == 2
    assert len(result["records"]) == 2
    assert result["diagnostics"]["pages_read"] == 2
    assert result["diagnostics"]["max_records"] == 10
    assert result["diagnostics"]["status"] == "INCONCLUSIVE"
    assert result["diagnostics"]["reason"] == "max_pages_reached"
    assert result["errors"] == [
        expected_error("pagination_limit_reached", "The pagination safety limit was reached.")
    ]
    assert result["diagnostics"]["pagination_limit_reached"] is True
    assert_no_sensitive_output(result)


def test_graphql_error_returns_sanitized_error_category():
    from crm_mcp_server.projects import crm_list_projects

    transport = RecordingTransport(
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
    )

    result = crm_list_projects(valid_request(max_records=1), transport=transport)

    assert result["records"] == []
    assert result["source_refs"] == []
    assert result["errors"] == [expected_error("graphql_error", "The CRM query returned an error.")]
    assert result["diagnostics"]["status"] == "ERROR"
    assert result["diagnostics"]["reason"] == "graphql_error"
    assert result["diagnostics"]["graphql_errors_count"] == 1
    assert result["diagnostics"]["mutation_used"] is False
    assert_no_sensitive_output(result)


def test_missing_required_source_id_returns_sanitized_normalization_error():
    from crm_mcp_server.projects import crm_list_projects

    transport = RecordingTransport([list_project_response([{**project_record("project-1"), "id": ""}])])

    result = crm_list_projects(valid_request(max_records=1), transport=transport)

    assert result["records"] == []
    assert result["source_refs"] == []
    assert result["errors"] == [
        expected_error("missing_required_fields", "The CRM response is missing required fields.")
    ]
    assert result["diagnostics"]["status"] == "ERROR"
    assert result["diagnostics"]["reason"] == "missing_required_fields"
    assert result["diagnostics"]["mutation_used"] is False
    assert_no_sensitive_output(result)


def test_empty_result_returns_empty_records_and_sanitized_diagnostics():
    from crm_mcp_server.projects import crm_list_projects

    transport = RecordingTransport([list_project_response([], total=0)])

    result = crm_list_projects(valid_request(max_records=5), transport=transport)

    assert result["records"] == []
    assert result["source_refs"] == []
    assert result["errors"] == []
    assert result["diagnostics"]["status"] == "INCONCLUSIVE"
    assert result["diagnostics"]["reason"] == "empty_result"
    assert result["diagnostics"]["mutation_used"] is False
    assert_no_sensitive_output(result)


def test_mutation_used_is_always_false_and_write_like_tool_names_remain_hidden():
    from crm_mcp_server.contract import list_v1_tools
    from crm_mcp_server.projects import crm_list_projects

    transport = RecordingTransport([list_project_response([project_record("project-1")])])

    result = crm_list_projects(valid_request(max_records=1), transport=transport)

    assert result["diagnostics"]["mutation_used"] is False
    for tool_name in list_v1_tools():
        assert "create" not in tool_name
        assert "update" not in tool_name
        assert "delete" not in tool_name
        assert "mutation" not in tool_name


def assert_no_sensitive_output(result: dict[str, object]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized
