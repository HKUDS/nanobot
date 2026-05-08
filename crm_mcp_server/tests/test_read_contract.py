from __future__ import annotations

import socket

import pytest

CANONICAL_V1_QUERIES = (
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
)


def test_v1_query_allow_list_matches_canonical_docs():
    from crm_mcp_server.contract import V1_ALLOWED_QUERY_NAMES, list_v1_query_names

    assert V1_ALLOWED_QUERY_NAMES == CANONICAL_V1_QUERIES
    assert tuple(list_v1_query_names()) == CANONICAL_V1_QUERIES


def test_allow_listed_query_can_construct_fixed_operation():
    from crm_mcp_server.graphql import build_read_operation

    operation = build_read_operation(
        "listProject",
        variables={"search": {"skip": 0, "limit": 10}},
    )

    assert operation.operation_type == "query"
    assert operation.operation_name == "listProject"
    assert operation.variables == {"search": {"skip": 0, "limit": 10}}
    assert operation.query.startswith("query listProject")
    assert "listProject" in operation.query
    assert "mutation" not in operation.query.lower()


def test_fixed_selection_set_omits_sensitive_contact_fields():
    from crm_mcp_server.graphql import build_read_operation

    sensitive_fragments = ("phone", "email", "address", "contact", "attachment")

    operation = build_read_operation("companyInfo", variables={"id": "synthetic-company"})
    selection = operation.query.lower()

    for fragment in sensitive_fragments:
        assert fragment not in selection


def test_build_read_operation_does_not_open_network(monkeypatch):
    from crm_mcp_server.graphql import build_read_operation

    connected_addresses: list[object] = []

    def fake_connect(self: socket.socket, address):
        connected_addresses.append(address)
        raise AssertionError("read contract construction must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", fake_connect)

    operation = build_read_operation("listReport", variables={"search": {"skip": 0, "limit": 1}})

    assert operation.operation_name == "listReport"
    assert connected_addresses == []


def test_unknown_operation_is_rejected():
    from crm_mcp_server.graphql import GraphQLContractError, build_read_operation

    with pytest.raises(GraphQLContractError, match="not allow-listed"):
        build_read_operation("unknownQuery")
