from __future__ import annotations

import json
import socket
import urllib.error
from pathlib import Path

import pytest

SENSITIVE_MARKERS = (
    "fake-token-123",
    "Authorization",
    "Bearer",
    "cookie",
    "http://crm.example.internal/query",
    "raw GraphQL request",
    "raw GraphQL response",
    "variables",
    "query listProject",
    "Synthetic Customer Name",
    "Synthetic Project Name",
    "contact",
    "phone",
    "email",
    "amount",
    "address",
    "free-text CRM note",
    "proxy.example.internal",
)


class FakeTransport:
    def __init__(self, response: dict[str, object], http_status_category: str = "success") -> None:
        self.response = response
        self.http_status_category = http_status_category
        self.auth_mode = "bearer"
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def execute(self, operation_name: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation_name, query, variables))
        return self.response


class FakeHTTPResponse:
    def __init__(self, *, status: int, body: bytes) -> None:
        self.status = status
        self.body = body

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_missing_env_returns_config_missing_without_transport_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm_mcp_server.real_smoke import run_real_crm_smoke

    monkeypatch.delenv("CRM_GRAPHQL_ENDPOINT", raising=False)
    monkeypatch.delenv("CRM_GRAPHQL_TOKEN", raising=False)
    transport = FakeTransport(response={"data": {"listProject": {"data": [{}]}}})

    result = run_real_crm_smoke(transport=transport)

    assert result["status"] == "INCONCLUSIVE"
    assert result["reason"] == "config_missing"
    assert result["runtime_enabled"] is False
    assert result["auth_mode"] == "bearer"
    assert transport.calls == []
    assert_no_sensitive_output(result)


def test_fake_transport_one_record_returns_sanitized_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm_mcp_server.real_smoke import run_real_crm_smoke

    set_fake_runtime_env(monkeypatch)
    transport = FakeTransport(
        response={
            "data": {
                "listProject": {
                    "data": [
                        {
                            "id": "synthetic-project-1",
                            "name": "Synthetic Project Name",
                            "customer": {"name": "Synthetic Customer Name"},
                            "contact": "contact",
                            "phone": "phone",
                            "email": "email",
                            "amount": "amount",
                            "address": "address",
                            "note": "free-text CRM note",
                        }
                    ],
                    "total": 1,
                }
            }
        }
    )

    result = run_real_crm_smoke(transport=transport)

    assert result["status"] == "OK"
    assert result["reason"] == "ok"
    assert result["data_count"] == 1
    assert result["normalized_count"] == 1
    assert result["mutation_used"] is False
    assert_no_sensitive_output(result)


def test_unauthorized_result_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm_mcp_server.real_smoke import run_real_crm_smoke

    set_fake_runtime_env(monkeypatch)
    transport = FakeTransport(
        response={"errors": [{"message": "Authorization Bearer fake-token-123 denied"}]},
        http_status_category="unauthorized_or_forbidden",
    )

    result = run_real_crm_smoke(transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "unauthorized_or_forbidden"
    assert result["auth_mode"] == "bearer"
    assert result["auth_error_category"] == "transport_auth_rejected"
    assert result["http_status_category"] == "unauthorized_or_forbidden"
    assert result["errors"] == [
        {
            "category": "unauthorized_or_forbidden",
            "message": "CRM access is unauthorized or forbidden.",
            "retryable": False,
        }
    ]
    assert_no_sensitive_output(result)


def test_graphql_error_result_uses_count_and_sanitized_category(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm_mcp_server.real_smoke import run_real_crm_smoke

    set_fake_runtime_env(monkeypatch)
    transport = FakeTransport(
        response={
            "errors": [
                {
                    "message": "raw GraphQL response for Synthetic Customer Name fake-token-123",
                    "extensions": {"variables": {"name": "Synthetic Project Name"}},
                }
            ]
        }
    )

    result = run_real_crm_smoke(transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "graphql_error"
    assert result["graphql_errors_count"] == 1
    assert result["graphql_error_category"] == "graphql_unknown_error"
    assert result["auth_error_category"] is None
    assert result["graphql_error_path_present"] is False
    assert result["graphql_error_extensions_present"] is True
    assert result["errors"] == [
        {"category": "graphql_error", "message": "The CRM query returned an error.", "retryable": False}
    ]
    assert_no_sensitive_output(result)


@pytest.mark.parametrize(
    ("error", "expected_category"),
    [
        (
            {"message": "Cannot query field raw GraphQL response fake-token-123", "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}},
            "graphql_unknown_field",
        ),
        (
            {"message": "Variable sort_by of required type SortBy! was not provided"},
            "graphql_variable_error",
        ),
        (
            {"message": "Forbidden scope Authorization Bearer fake-token-123", "extensions": {"code": "FORBIDDEN"}},
            "graphql_auth_scope_error",
        ),
        (
            {"message": "Resolver internal execution failure", "path": ["listProject"], "extensions": {"code": "INTERNAL_SERVER_ERROR"}},
            "graphql_execution_error",
        ),
        (
            {"message": "raw GraphQL response Synthetic Customer Name Synthetic Project Name amount contact free-text CRM note"},
            "graphql_unknown_error",
        ),
    ],
)
def test_graphql_error_categories_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    error: dict[str, object],
    expected_category: str,
) -> None:
    from crm_mcp_server.real_smoke import run_real_crm_smoke

    set_fake_runtime_env(monkeypatch)
    transport = FakeTransport(response={"errors": [error]})

    result = run_real_crm_smoke(transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "graphql_error"
    assert result["graphql_errors_count"] == 1
    assert result["graphql_error_category"] == expected_category
    assert result["graphql_error_path_present"] is ("path" in error)
    assert result["graphql_error_extensions_present"] is ("extensions" in error)
    assert result["errors"] == [
        {"category": "graphql_error", "message": "The CRM query returned an error.", "retryable": False}
    ]
    assert_no_sensitive_output(result)


def test_not_login_graphql_error_sets_sanitized_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm_mcp_server.real_smoke import run_real_crm_smoke

    set_fake_runtime_env(monkeypatch)
    transport = FakeTransport(response={"errors": [{"message": "not login"}]})

    result = run_real_crm_smoke(transport=transport)

    assert result["status"] == "ERROR"
    assert result["reason"] == "graphql_error"
    assert result["graphql_error_category"] == "graphql_auth_scope_error"
    assert result["auth_error_category"] == "not_login"
    assert result["auth_mode"] == "bearer"
    assert_no_sensitive_output(result)


def test_default_real_smoke_auth_mode_uses_bearer_header_without_stdout_leak(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from crm_mcp_server import real_smoke

    captured_headers: dict[str, str] = {}
    set_fake_runtime_env(monkeypatch)

    def fake_urlopen(request: object, timeout: float) -> FakeHTTPResponse:
        captured_headers.update(dict(request.header_items()))
        return FakeHTTPResponse(status=200, body=b'{"data":{"listProject":{"data":[]}}}')

    monkeypatch.setattr(real_smoke.urllib.request, "urlopen", fake_urlopen)

    exit_code = real_smoke.main([])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["auth_mode"] == "bearer"
    assert next((value for key, value in captured_headers.items() if key.lower() == "authorization"), None) == "Bearer fake-token-123"
    assert not any(key.lower() == "private-token" for key in captured_headers)
    assert captured.err == ""
    assert_no_sensitive_output(result)
    assert_no_sensitive_output({"stdout": captured.out})


@pytest.mark.parametrize(
    ("auth_mode", "expected_header"),
    [
        ("private_token", "Private-Token"),
        ("bearer", "Authorization"),
        ("cookie", "Cookie"),
    ],
)
def test_real_transport_uses_selected_auth_mode_header(
    monkeypatch: pytest.MonkeyPatch,
    auth_mode: str,
    expected_header: str,
) -> None:
    from crm_mcp_server import real_smoke

    captured_headers: dict[str, str] = {}
    config = real_smoke.RealSmokeConfig(endpoint="http://crm.example.internal/query", token="fake-token-123", auth_mode=auth_mode)
    transport = real_smoke.RealGraphQLSmokeTransport(config=config)

    def fake_urlopen(request: object, timeout: float) -> FakeHTTPResponse:
        captured_headers.update(dict(request.header_items()))
        return FakeHTTPResponse(status=200, body=b'{"data":{"listProject":{"data":[]}}}')

    monkeypatch.setattr(real_smoke.urllib.request, "urlopen", fake_urlopen)

    response = transport.execute("listProject", "query listProject { listProject { data { id } } }", {})

    assert response == {"data": {"listProject": {"data": []}}}
    assert transport.auth_mode == auth_mode
    matching_header = next((value for key, value in captured_headers.items() if key.lower() == expected_header.lower()), None)
    assert matching_header is not None
    assert "fake-token-123" in matching_header


def test_main_accepts_auth_mode_without_leaking_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from crm_mcp_server import real_smoke

    set_fake_runtime_env(monkeypatch)
    def fake_transport(config: object) -> FakeTransport:
        transport = FakeTransport({"errors": [{"message": "not login"}]})
        transport.auth_mode = config.auth_mode
        return transport

    monkeypatch.setattr(real_smoke, "RealGraphQLSmokeTransport", fake_transport)

    exit_code = real_smoke.main(["--auth-mode", "bearer"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["auth_mode"] == "bearer"
    assert result["auth_error_category"] == "not_login"
    assert_no_sensitive_output(result)
    assert_no_sensitive_output({"stdout": captured.out})


def test_module_stdout_excludes_raw_graphql_error_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from crm_mcp_server import real_smoke

    class GraphQLErrorTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__(
                response={
                    "errors": [
                        {
                            "message": "raw GraphQL response variables fake-token-123 Synthetic Customer Name amount contact free-text CRM note",
                            "path": ["listProject"],
                            "extensions": {"code": "INTERNAL_SERVER_ERROR", "Authorization": "Bearer fake-token-123"},
                        }
                    ]
                }
            )

    set_fake_runtime_env(monkeypatch)
    monkeypatch.setattr(real_smoke, "RealGraphQLSmokeTransport", lambda config: GraphQLErrorTransport())

    exit_code = real_smoke.main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["reason"] == "graphql_error"
    assert result["graphql_error_category"] == "graphql_execution_error"
    assert result["graphql_error_path_present"] is True
    assert result["graphql_error_extensions_present"] is True
    assert captured.err == ""
    assert_no_sensitive_output(result)
    assert_no_sensitive_output({"stdout": captured.out})


def test_real_transport_repr_does_not_disclose_runtime_values() -> None:
    from crm_mcp_server.real_smoke import RealGraphQLSmokeTransport, RealSmokeConfig

    config = RealSmokeConfig(endpoint="http://crm.example.internal/query", token="fake-token-123", auth_mode="private_token")
    transport = RealGraphQLSmokeTransport(config=config)

    rendered = repr(config) + repr(transport)

    assert "http://crm.example.internal/query" not in rendered
    assert "fake-token-123" not in rendered


def test_real_smoke_uses_fixed_list_project_limit_one_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm_mcp_server.real_smoke import run_real_crm_smoke

    set_fake_runtime_env(monkeypatch)
    transport = FakeTransport(response={"data": {"listProject": {"data": []}}})

    result = run_real_crm_smoke(transport=transport)

    operation_name, query, variables = transport.calls[0]

    assert operation_name == "listProject"
    assert variables == {
        "search": {},
        "pagination": {"skip": 0, "limit": 1},
        "sort_by": {"by": "updatedAt", "order": -1},
    }
    assert "$search: ProjectSearchParam!" in query
    assert "$pagination: PaginationParam" in query
    assert "$sort_by: SortBy!" in query
    assert "listProject(search: $search, pagination: $pagination, sort_by: $sort_by)" in query
    assert "mutation" not in query.lower()
    assert result["mutation_used"] is False


def test_module_main_prints_sanitized_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from crm_mcp_server.real_smoke import main

    monkeypatch.delenv("CRM_GRAPHQL_ENDPOINT", raising=False)
    monkeypatch.delenv("CRM_GRAPHQL_TOKEN", raising=False)

    exit_code = main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "INCONCLUSIVE"
    assert result["reason"] == "config_missing"
    assert captured.err == ""
    assert_no_sensitive_output(result)


def test_default_main_does_not_output_raw_graphql_error_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from crm_mcp_server import real_smoke

    class RawErrorTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__(response=raw_graphql_error_response())

    set_fake_runtime_env(monkeypatch)
    monkeypatch.setattr(real_smoke, "RealGraphQLSmokeTransport", lambda config: RawErrorTransport())

    exit_code = real_smoke.main([])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["reason"] == "graphql_error"
    assert "LOCAL ONLY" not in captured.out
    assert "cannot query sanitized_field" not in captured.out
    assert_no_sensitive_output(result)
    assert_no_sensitive_output({"stdout": captured.out})


def test_inspect_mode_requires_explicit_arg(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from crm_mcp_server import real_smoke

    set_fake_runtime_env(monkeypatch)
    monkeypatch.setattr(real_smoke, "RealGraphQLSmokeTransport", lambda config: FakeTransport(raw_graphql_error_response()))

    real_smoke.main([])
    default_output = capsys.readouterr().out
    real_smoke.main(["--inspect-graphql-error-local"])
    inspect_output = capsys.readouterr().out

    assert "cannot query sanitized_field" not in default_output
    assert "cannot query sanitized_field" in inspect_output


def test_inspect_mode_warns_and_redacts_sensitive_markers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from crm_mcp_server import real_smoke

    set_fake_runtime_env(monkeypatch)
    monkeypatch.setattr(real_smoke, "RealGraphQLSmokeTransport", lambda config: FakeTransport(raw_graphql_error_response()))

    exit_code = real_smoke.main(["--inspect-graphql-error-local"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "LOCAL ONLY" in captured.out
    assert "do not paste output into chat" in captured.out
    assert "do not commit output" in captured.out
    assert "cannot query sanitized_field" in captured.out
    assert "[REDACTED_ENDPOINT]" in captured.out
    assert "[REDACTED_AUTH]" in captured.out
    assert "raw GraphQL request" not in captured.out
    assert "raw GraphQL response" not in captured.out
    assert "variables" not in captured.out
    assert_no_sensitive_output({"stdout": captured.out})
    assert captured.err == ""


def test_module_stdout_excludes_raw_query_variables_endpoint_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from crm_mcp_server import real_smoke

    class SensitiveTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__(
                response={
                    "data": {
                        "listProject": {
                            "data": [
                                {
                                    "token": "fake-token-123",
                                    "project": "Synthetic Project Name",
                                    "customer": "Synthetic Customer Name",
                                    "name": "Synthetic Customer Name",
                                    "amount": "amount",
                                    "contact": "contact",
                                    "note": "free-text CRM note",
                                }
                            ]
                        }
                    }
                }
            )

    set_fake_runtime_env(monkeypatch)
    transport = SensitiveTransport()
    monkeypatch.setattr(real_smoke, "RealGraphQLSmokeTransport", lambda config: transport)

    exit_code = real_smoke.main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["status"] == "OK"
    assert captured.err == ""
    assert_no_sensitive_output(result)
    assert_no_sensitive_output({"stdout": captured.out})


@pytest.mark.parametrize(
    ("raised", "expected_category"),
    [
        (TimeoutError(), "connect_timeout"),
        (urllib.error.URLError(socket.gaierror()), "dns_error"),
        (urllib.error.URLError(ConnectionRefusedError()), "connection_refused"),
    ],
)
def test_real_transport_maps_network_errors_to_sanitized_categories(
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    expected_category: str,
) -> None:
    from crm_mcp_server import real_smoke

    set_fake_runtime_env(monkeypatch)

    def fail_urlopen(request: object, timeout: float) -> object:
        raise raised

    monkeypatch.setattr(real_smoke.urllib.request, "urlopen", fail_urlopen)

    result = real_smoke.run_real_crm_smoke()

    assert result["status"] == "ERROR"
    assert result["reason"] == "crm_unavailable"
    assert result["transport_attempted"] is True
    assert result["transport_error_category"] == expected_category
    assert result["http_status_category"] == "crm_unavailable"
    assert result["status_code_category"] == "not_available"
    assert result["endpoint_configured"] is True
    assert result["token_configured"] is True
    assert result["proxy_configured"] is False
    assert result["data_count"] == 0
    assert result["graphql_errors_count"] == 0
    assert_no_sensitive_output(result)


@pytest.mark.parametrize(
    ("status_code", "expected_http_category", "expected_reason", "expected_transport_category", "expected_status_code_category"),
    [
        (401, "unauthorized_or_forbidden", "unauthorized_or_forbidden", "http_4xx", "4xx"),
        (403, "unauthorized_or_forbidden", "unauthorized_or_forbidden", "http_4xx", "4xx"),
        (500, "crm_unavailable", "crm_unavailable", "http_5xx", "5xx"),
    ],
)
def test_real_transport_maps_http_errors_to_sanitized_categories(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_http_category: str,
    expected_reason: str,
    expected_transport_category: str,
    expected_status_code_category: str,
) -> None:
    from crm_mcp_server import real_smoke

    set_fake_runtime_env(monkeypatch)

    def fail_urlopen(request: object, timeout: float) -> object:
        raise urllib.error.HTTPError(
            url="http://crm.example.internal/query",
            code=status_code,
            msg="raw GraphQL response fake-token-123 Synthetic Customer Name",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(real_smoke.urllib.request, "urlopen", fail_urlopen)

    result = real_smoke.run_real_crm_smoke()

    assert result["status"] == "ERROR"
    assert result["reason"] == expected_reason
    assert result["transport_error_category"] == expected_transport_category
    assert result["http_status_category"] == expected_http_category
    assert result["status_code_category"] == expected_status_code_category
    assert_no_sensitive_output(result)


def test_real_transport_maps_success_non_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm_mcp_server import real_smoke

    set_fake_runtime_env(monkeypatch)
    monkeypatch.setattr(
        real_smoke.urllib.request,
        "urlopen",
        lambda request, timeout: FakeHTTPResponse(status=200, body=b"raw GraphQL response fake-token-123"),
    )

    result = real_smoke.run_real_crm_smoke()

    assert result["status"] == "ERROR"
    assert result["reason"] == "crm_unavailable"
    assert result["transport_error_category"] == "non_json_response"
    assert result["response_json_parsed"] is False
    assert result["http_status_category"] == "success"
    assert result["status_code_category"] == "2xx"
    assert_no_sensitive_output(result)


def test_real_transport_success_empty_json_shape_is_invalid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm_mcp_server import real_smoke

    set_fake_runtime_env(monkeypatch)
    monkeypatch.setattr(
        real_smoke.urllib.request,
        "urlopen",
        lambda request, timeout: FakeHTTPResponse(status=200, body=b"{}"),
    )

    result = real_smoke.run_real_crm_smoke()

    assert result["status"] == "ERROR"
    assert result["reason"] == "invalid_response"
    assert result["transport_error_category"] is None
    assert result["response_json_parsed"] is True
    assert result["http_status_category"] == "success"
    assert result["status_code_category"] == "2xx"
    assert result["data_root_present"] is False
    assert_no_sensitive_output(result)


def test_module_stdout_reports_proxy_as_boolean_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from crm_mcp_server import real_smoke

    set_fake_runtime_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.internal:8080")
    monkeypatch.setattr(
        real_smoke.urllib.request,
        "urlopen",
        lambda request, timeout: FakeHTTPResponse(status=200, body=b"not-json"),
    )

    exit_code = real_smoke.main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["proxy_configured"] is True
    assert "proxy.example.internal" not in captured.out
    assert captured.err == ""
    assert_no_sensitive_output(result)
    assert_no_sensitive_output({"stdout": captured.out})


def test_real_smoke_source_has_no_sensitive_print_or_logging_patterns() -> None:
    text = Path("crm_mcp_server/crm_mcp_server/real_smoke.py").read_text()
    forbidden_output_patterns = [
        "print(os.environ",
        "print(endpoint",
        "print(token",
        "logger.info(endpoint",
        "logger.info(token",
        "logger.debug(endpoint",
        "logger.debug(token",
    ]

    hits = [item for item in forbidden_output_patterns if item in text]

    assert not hits


def set_fake_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRM_GRAPHQL_ENDPOINT", "http://crm.example.internal/query")
    monkeypatch.setenv("CRM_GRAPHQL_TOKEN", "fake-token-123")


def raw_graphql_error_response() -> dict[str, object]:
    return {
        "errors": [
            {
                "message": (
                    "cannot query sanitized_field at http://crm.example.internal/query with "
                    "Authorization Bearer fake-token-123 cookie session=abc raw GraphQL request "
                    "raw GraphQL response variables Synthetic Customer Name Synthetic Project Name "
                    "amount contact phone email address free-text CRM note"
                )
            }
        ]
    }


def assert_no_sensitive_output(result: dict[str, object]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized
