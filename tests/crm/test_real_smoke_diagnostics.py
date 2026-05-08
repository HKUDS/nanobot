from __future__ import annotations

import pytest

from nanobot.crm.real_smoke_diagnostics import run_list_project_diagnostics

FAKE_ENDPOINT = "https://synthetic.invalid/graphql"
FAKE_TOKEN = "fake-token-for-diagnostics"


class DiagnosticTransport:
    def __init__(self, response: dict[str, object] | None = None, exc: Exception | None = None, status: int = 200) -> None:
        self.response = response or {}
        self.exc = exc
        self.status = status
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, endpoint: str, token: str, operation_name: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append(
            {
                "endpoint": endpoint,
                "token": token,
                "operation_name": operation_name,
                "query": query,
                "variables": variables,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.response


def test_diagnostics_reports_empty_connection_without_business_values() -> None:
    transport = DiagnosticTransport(
        response={"data": {"listProject": {"total": 0, "skip": 0, "limit": 1, "data": []}}}
    )

    result = run_list_project_diagnostics(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=transport)

    assert result["endpoint_present"] is True
    assert result["token_present"] is True
    assert result["operation_name"] == "listProject"
    assert result["mutation_used"] is False
    assert result["limit"] == 1
    assert result["http_reached"] is True
    assert result["http_status_category"] == "2xx"
    assert result["top_level_field_present"] is True
    assert result["connection_present"] is True
    assert result["connection_total_present"] is True
    assert result["data_count"] == 0
    assert result["normalized_count"] == 0
    assert result["root_cause_category"] == "empty_connection"
    assert transport.calls[0]["operation_name"] == "listProject"
    assert transport.calls[0]["variables"]["pagination"] == {"skip": 0, "limit": 1}


def test_diagnostics_sanitizes_graphql_errors_and_raw_payload() -> None:
    raw_marker = "RAW_CUSTOMER_PROJECT_NAME_SHOULD_NOT_LEAK"
    transport = DiagnosticTransport(
        response={
            "errors": [
                {
                    "message": f"Unauthorized Authorization Bearer {FAKE_TOKEN} {raw_marker}",
                    "extensions": {"raw_payload": raw_marker},
                }
            ]
        }
    )

    result = run_list_project_diagnostics(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=transport)
    serialized = repr(result)

    assert result["graphql_errors_count"] == 1
    assert result["root_cause_category"] == "unauthorized_or_forbidden"
    assert result["graphql_error_categories"] == ("authorization",)
    assert FAKE_TOKEN not in serialized
    assert "Authorization" not in serialized
    assert "Bearer" not in serialized
    assert raw_marker not in serialized


def test_diagnostics_reports_first_record_field_presence_without_values() -> None:
    transport = DiagnosticTransport(
        response={
            "data": {
                "listProject": {
                    "total": 1,
                    "skip": 0,
                    "limit": 1,
                    "data": [
                        {
                            "id": "REAL_PROJECT_NAME_SHOULD_NOT_LEAK",
                            "name": "REAL_CUSTOMER_NAME_SHOULD_NOT_LEAK",
                            "updated_at": "2026-01-15T10:00:00+00:00",
                            "created_at": "2026-01-10T09:00:00+00:00",
                            "stage": "proposal",
                            "claimBy": {"user": {"id": "REAL_USER_SHOULD_NOT_LEAK", "name": "REAL_NAME_SHOULD_NOT_LEAK"}},
                            "company": {"id": "REAL_COMPANY_SHOULD_NOT_LEAK", "name": "REAL_COMPANY_NAME_SHOULD_NOT_LEAK"},
                            "amount": {"value": "999999", "currency": "CNY"},
                        }
                    ],
                }
            }
        }
    )

    result = run_list_project_diagnostics(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=transport)
    serialized = repr(result)

    assert result["data_count"] == 1
    assert result["normalized_count"] == 1
    assert result["root_cause_category"] == "none"
    assert result["first_record_field_presence"] == {
        "id": True,
        "name": True,
        "updated_at": True,
        "created_at": True,
        "stage": True,
        "claimBy": True,
        "company": True,
        "amount": True,
        "actual_amount": False,
    }
    for forbidden in (
        "REAL_PROJECT_NAME_SHOULD_NOT_LEAK",
        "REAL_CUSTOMER_NAME_SHOULD_NOT_LEAK",
        "REAL_COMPANY_NAME_SHOULD_NOT_LEAK",
        "999999",
    ):
        assert forbidden not in serialized


def test_diagnostics_reports_network_error_without_calling_mutation() -> None:
    transport = DiagnosticTransport(exc=TimeoutError(f"network failed with token {FAKE_TOKEN}"))

    result = run_list_project_diagnostics(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=transport)
    serialized = repr(result)

    assert result["http_reached"] is False
    assert result["http_status_category"] == "network_error"
    assert result["root_cause_category"] == "network_unreachable"
    assert transport.calls[0]["operation_name"] == "listProject"
    assert "mutation" not in transport.calls[0]["query"].lower()
    assert FAKE_TOKEN not in serialized


@pytest.mark.parametrize(("endpoint", "token"), [("", FAKE_TOKEN), (FAKE_ENDPOINT, "")])
def test_diagnostics_reports_missing_config_without_transport(endpoint: str, token: str) -> None:
    transport = DiagnosticTransport()

    result = run_list_project_diagnostics(endpoint=endpoint, token=token, transport=transport)

    assert result["root_cause_category"] == "config_missing"
    assert result["http_reached"] is False
    assert transport.calls == []
