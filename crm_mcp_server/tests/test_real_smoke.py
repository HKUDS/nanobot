from __future__ import annotations

import json
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
    "Synthetic Customer Name",
    "Synthetic Project Name",
    "contact",
    "phone",
    "email",
    "amount",
    "address",
    "free-text CRM note",
)


class FakeTransport:
    def __init__(self, response: dict[str, object], http_status_category: str = "success") -> None:
        self.response = response
        self.http_status_category = http_status_category
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def execute(self, operation_name: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation_name, query, variables))
        return self.response


def test_missing_env_returns_config_missing_without_transport_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from crm_mcp_server.real_smoke import run_real_crm_smoke

    monkeypatch.delenv("CRM_GRAPHQL_ENDPOINT", raising=False)
    monkeypatch.delenv("CRM_GRAPHQL_TOKEN", raising=False)
    transport = FakeTransport(response={"data": {"listProject": {"data": [{}]}}})

    result = run_real_crm_smoke(transport=transport)

    assert result["status"] == "INCONCLUSIVE"
    assert result["reason"] == "config_missing"
    assert result["runtime_enabled"] is False
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
    assert result["errors"] == [
        {"category": "graphql_error", "message": "The CRM query returned an error.", "retryable": False}
    ]
    assert_no_sensitive_output(result)


def test_real_transport_repr_does_not_disclose_runtime_values() -> None:
    from crm_mcp_server.real_smoke import RealGraphQLSmokeTransport, RealSmokeConfig

    config = RealSmokeConfig(endpoint="http://crm.example.internal/query", token="fake-token-123")
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
    assert variables == {"search": {"skip": 0, "limit": 1}}
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


def assert_no_sensitive_output(result: dict[str, object]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized
