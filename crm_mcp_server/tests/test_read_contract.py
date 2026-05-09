from __future__ import annotations

import socket

import pytest

CANONICAL_V1_QUERIES = (
    "listReport",
    "reportInfo",
    "reportRelatedInfo",
    "listProject",
    "listProjectID",
    "projectInfo",
    "listActivity",
    "listCompany",
    "companyInfo",
    "listUser",
    "list_leads",
    "list_leads_pool",
    "list_opportunity_scenario",
    "listImmediatelySignProject",
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
        variables={
            "search": {},
            "pagination": {"skip": 0, "limit": 10},
            "sort_by": {"by": "updatedAt", "order": -1},
        },
    )

    assert operation.operation_type == "query"
    assert operation.operation_name == "listProject"
    assert operation.variables == {
        "search": {},
        "pagination": {"skip": 0, "limit": 10},
        "sort_by": {"by": "updatedAt", "order": -1},
    }
    assert operation.query.startswith("query listProject")
    assert "$search: ProjectSearchParam!" in operation.query
    assert "$pagination: PaginationParam" in operation.query
    assert "$sort_by: SortBy!" in operation.query
    assert "listProject(search: $search, pagination: $pagination, sort_by: $sort_by)" in operation.query
    assert "claimBy { id user { name } }" in operation.query
    assert "mutation" not in operation.query.lower()


def test_list_business_chance_binds_scoped_search_variable_to_field():
    from crm_mcp_server.graphql import build_read_operation

    operation = build_read_operation(
        "list_business_chance",
        variables={
            "search": {
                "start": "2026-01-01",
                "end": "2026-01-31",
                "scope_id": "synthetic-team",
            },
            "pagination": {"skip": 0, "limit": 10},
        },
    )

    assert operation.query.startswith(
        "query list_business_chance($search: BusinessChanceSearchParam, $pagination: PaginationParam)"
    )
    assert "list_business_chance(search: $search, pagination: $pagination)" in operation.query
    assert "$id" not in operation.query


def test_report_assistant_list_query_binds_search_variable_to_field():
    from crm_mcp_server.graphql import build_read_operation

    operation = build_read_operation(
        "list_leads",
        variables={"search": {"list_type": "claim_by"}, "pagination": {"skip": 0, "limit": 10}},
    )

    assert operation.query.startswith(
        "query list_leads($search: LeadsSearchParam, $pagination: PaginationParam)"
    )
    assert "list_leads(search: $search, pagination: $pagination)" in operation.query
    assert "$id" not in operation.query


def test_build_read_operation_drops_variables_not_declared_by_fixed_query():
    from crm_mcp_server.graphql import build_read_operation

    operation = build_read_operation(
        "list_leads",
        variables={
            "search": {"list_type": "claim_by"},
            "id": "synthetic-lead",
            "unexpected": "value",
        },
    )

    assert operation.query.startswith("query list_leads($search: LeadsSearchParam)")
    assert "list_leads(search: $search)" in operation.query
    assert "$id" not in operation.query
    assert "$unexpected" not in operation.query
    assert operation.variables == {"search": {"list_type": "claim_by"}}


def test_query_without_variables_declares_no_unused_variables():
    from crm_mcp_server.graphql import build_read_operation

    operation = build_read_operation("list_leads")

    first_line = operation.query.splitlines()[0]

    assert first_line == "query list_leads {"
    assert "list_leads {" in operation.query
    assert "$search" not in operation.query
    assert "$id" not in operation.query


@pytest.mark.parametrize(
    "operation_name",
    (
        "listProjectID",
        "list_leads",
        "list_leads_pool",
        "list_opportunity_scenario",
        "listImmediatelySignProject",
    ),
)
def test_report_assistant_source_queries_construct_fixed_operations(operation_name: str):
    from crm_mcp_server.graphql import build_read_operation

    operation = build_read_operation(operation_name)

    assert operation.operation_type == "query"
    assert operation.operation_name == operation_name
    assert operation.query.startswith(f"query {operation_name}")
    if operation_name != "listProjectID":
        assert f"{operation_name} {{" in operation.query
    if operation_name == "listProjectID":
        assert "listProjectID" in operation.query
    else:
        assert " id" in operation.query
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
