from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nanobot.crm.adapters import CRMAdapterErrorCode
from nanobot.crm.graphql_client import CRMGraphQLClient, CRMGraphQLClientError

FAKE_ENDPOINT = "https://synthetic.invalid/graphql"
FAKE_TOKEN = "fake-token-for-tests"


class FakeTransport:
    def __init__(self, response: dict[str, object] | None = None, exc: Exception | None = None) -> None:
        self.response = response or {"data": {"listProject": {"total": 0, "skip": 0, "limit": 10, "data": []}}}
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        *,
        endpoint: str,
        token: str,
        operation_name: str,
        query: str,
        variables: dict[str, object],
    ) -> dict[str, object]:
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


def test_allow_listed_query_succeeds_with_fake_transport() -> None:
    transport = FakeTransport(response={"data": {"listProject": {"total": 1, "data": []}}})
    client = CRMGraphQLClient(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=transport)

    result = client.query(
        "listProject",
        "query listProject($pagination: PaginationParam) { listProject(search: {}, pagination: $pagination) { total data { id name } } }",
        {"pagination": {"skip": 0, "limit": 10}},
    )

    assert result == {"listProject": {"total": 1, "data": []}}
    assert transport.calls == [
        {
            "endpoint": FAKE_ENDPOINT,
            "token": FAKE_TOKEN,
            "operation_name": "listProject",
            "query": "query listProject($pagination: PaginationParam) { listProject(search: {}, pagination: $pagination) { total data { id name } } }",
            "variables": {"pagination": {"skip": 0, "limit": 10}},
        }
    ]


def test_unknown_query_is_rejected_before_transport() -> None:
    transport = FakeTransport()
    client = CRMGraphQLClient(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=transport)

    with pytest.raises(CRMGraphQLClientError) as exc_info:
        client.query("unknownQuery", "query unknownQuery { unknownQuery { id } }", {})

    assert exc_info.value.code is CRMAdapterErrorCode.INVALID_CONFIGURATION
    assert "unknownQuery" in str(exc_info.value)
    assert transport.calls == []


@pytest.mark.parametrize(
    ("operation_name", "query"),
    [
        ("createReport", "mutation createReport { createReport(input: {}) { id } }"),
        ("listProject", "mutation listProject { listProject(search: {}) { total } }"),
    ],
)
def test_mutation_is_rejected_even_when_operation_name_is_allow_listed(
    operation_name: str, query: str
) -> None:
    transport = FakeTransport()
    client = CRMGraphQLClient(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=transport)

    with pytest.raises(CRMGraphQLClientError) as exc_info:
        client.query(operation_name, query, {})

    assert exc_info.value.code is CRMAdapterErrorCode.INVALID_CONFIGURATION
    assert "mutation" in str(exc_info.value).lower()
    assert transport.calls == []


def test_graphql_errors_are_sanitized_and_do_not_include_token() -> None:
    transport = FakeTransport(
        response={
            "errors": [
                {
                    "message": f"backend rejected Authorization Bearer {FAKE_TOKEN}",
                    "path": ["listProject"],
                }
            ]
        }
    )
    client = CRMGraphQLClient(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=transport)

    with pytest.raises(CRMGraphQLClientError) as exc_info:
        client.query("listProject", "query listProject { listProject(search: {}) { total } }", {})

    message = str(exc_info.value)
    assert exc_info.value.code is CRMAdapterErrorCode.CRM_UNAVAILABLE
    assert FAKE_TOKEN not in message
    assert "Authorization" not in message
    assert "Bearer" not in message
    assert "<redacted>" in message
    assert FAKE_TOKEN not in repr(exc_info.value)


def test_network_errors_are_mapped_to_sanitized_unavailable_error() -> None:
    transport = FakeTransport(exc=RuntimeError(f"network failed with token {FAKE_TOKEN}"))
    client = CRMGraphQLClient(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=transport)

    with pytest.raises(CRMGraphQLClientError) as exc_info:
        client.query("listProject", "query listProject { listProject(search: {}) { total } }", {})

    assert exc_info.value.code is CRMAdapterErrorCode.CRM_UNAVAILABLE
    assert FAKE_TOKEN not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)
    assert "Bearer" not in str(exc_info.value)
    assert "<redacted>" in str(exc_info.value)


def test_endpoint_is_configurable_without_hardcoded_secret() -> None:
    endpoint = "https://synthetic-crm.example/graphql"
    transport = FakeTransport()
    client = CRMGraphQLClient(endpoint=endpoint, token=FAKE_TOKEN, transport=transport)

    client.query("listUser", "query listUser { listUser(search: {}) { total } }", {})

    assert transport.calls[0]["endpoint"] == endpoint


def test_graphql_client_module_has_no_real_transport_or_env_reads() -> None:
    source = Path("nanobot/crm/graphql_client.py").read_text()
    tree = ast.parse(source)

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    forbidden_imports = {"httpx", "requests", "urllib.request", "os", "dotenv"}
    forbidden_fragments = ("api.in.chaitin.net", ".env", "real_adapter")

    assert imports.isdisjoint(forbidden_imports)
    assert all(fragment not in source for fragment in forbidden_fragments)


def test_default_allowed_operations_match_contract_allow_list() -> None:
    client = CRMGraphQLClient(endpoint=FAKE_ENDPOINT, token=FAKE_TOKEN, transport=FakeTransport())

    assert client.allowed_operations == {
        "listReport",
        "reportInfo",
        "reportRelatedInfo",
        "listProject",
        "projectInfo",
        "listActivity",
        "listCompany",
        "companyInfo",
        "listUser",
        "list_business_chance",
        "business_chance",
    }
