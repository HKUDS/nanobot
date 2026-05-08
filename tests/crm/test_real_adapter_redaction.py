from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from nanobot.crm.adapters import CRMAdapterError, CRMAdapterErrorCode
from nanobot.crm.graphql_client import CRMGraphQLClient
from nanobot.crm.models import ReportRequest, ReportScope, ReportType, ReportWindow
from nanobot.crm.real_adapter import RealCRMAdapter

SYNTHETIC_ENDPOINT = "https://synthetic.invalid/graphql"
SYNTHETIC_CREDENTIAL = "synthetic-credential-value"


class ErrorTransport:
    def __init__(self, response: dict[str, object] | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls = 0

    def __call__(self, **_: object) -> dict[str, object]:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        assert self.response is not None
        return self.response


def _request() -> ReportRequest:
    return ReportRequest(
        report_type=ReportType.DAILY,
        window=ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15)),
        scope=ReportScope(scope_id="synthetic-team"),
    )


def _adapter(transport: ErrorTransport) -> RealCRMAdapter:
    client = CRMGraphQLClient(SYNTHETIC_ENDPOINT, SYNTHETIC_CREDENTIAL, transport)
    return RealCRMAdapter(client)


def test_crm_unavailable_error_is_sanitized() -> None:
    adapter = _adapter(ErrorTransport(exc=RuntimeError(f"network Authorization Bearer {SYNTHETIC_CREDENTIAL}")))

    with pytest.raises(CRMAdapterError) as exc_info:
        adapter.read_opportunities(_request())

    message = str(exc_info.value)
    assert exc_info.value.code is CRMAdapterErrorCode.CRM_UNAVAILABLE
    assert SYNTHETIC_CREDENTIAL not in message
    assert "Authorization" not in message
    assert "Bearer" not in message


def test_unauthorized_graphql_error_is_sanitized() -> None:
    adapter = _adapter(
        ErrorTransport(
            response={
                "errors": [
                    {
                        "message": f"Unauthorized Authorization: Bearer {SYNTHETIC_CREDENTIAL}",
                        "extensions": {"raw_payload": "RAW_SYNTHETIC_PAYLOAD_SHOULD_NOT_LEAK"},
                    }
                ]
            }
        )
    )

    with pytest.raises(CRMAdapterError) as exc_info:
        adapter.read_reports(_request())

    message = str(exc_info.value)
    assert exc_info.value.code is CRMAdapterErrorCode.CRM_UNAVAILABLE
    assert SYNTHETIC_CREDENTIAL not in message
    assert "Authorization" not in message
    assert "RAW_SYNTHETIC_PAYLOAD_SHOULD_NOT_LEAK" not in message


def test_real_adapter_source_has_no_env_endpoint_or_mutation_usage() -> None:
    source = Path("nanobot/crm/real_adapter.py").read_text()
    tree = ast.parse(source)

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert imports.isdisjoint({"httpx", "requests", "os", "dotenv"})
    assert "api.in.chaitin.net" not in source
    assert ".env" not in source
    assert "mutation" not in source.lower()
