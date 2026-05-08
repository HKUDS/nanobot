from __future__ import annotations

import inspect

import pytest

WRITE_LIKE_OPERATION_NAMES = (
    "createProject",
    "updateCompany",
    "deleteReport",
    "removeActivity",
    "assignProject",
    "claimBusinessChance",
    "transferCustomer",
    "sendMessage",
    "exportReport",
)


def test_operation_type_mutation_is_rejected():
    from crm_mcp_server.graphql import GraphQLContractError, build_read_operation

    with pytest.raises(GraphQLContractError, match="Mutation is forbidden"):
        build_read_operation("listProject", operation_type="mutation")


def test_query_string_containing_mutation_is_rejected():
    from crm_mcp_server.graphql import GraphQLContractError, validate_read_query_text

    with pytest.raises(GraphQLContractError, match="Mutation is forbidden"):
        validate_read_query_text("mutation listProject { listProject { total } }")


def test_write_like_operation_names_are_rejected():
    from crm_mcp_server.graphql import GraphQLContractError, build_read_operation

    for operation_name in WRITE_LIKE_OPERATION_NAMES:
        with pytest.raises(GraphQLContractError):
            build_read_operation(operation_name)


def test_raw_graphql_passthrough_is_not_exposed():
    import crm_mcp_server.graphql as graphql
    from crm_mcp_server.contract import list_v1_tools

    forbidden_names = {"run_graphql", "execute_query", "execute_graphql", "raw_query"}
    module_functions = {
        name
        for name, value in inspect.getmembers(graphql, inspect.isfunction)
        if not name.startswith("_")
    }
    build_signature = inspect.signature(graphql.build_read_operation)

    assert module_functions.isdisjoint(forbidden_names)
    assert set(list_v1_tools()).isdisjoint(forbidden_names)
    assert "query_override" not in build_signature.parameters
    assert "query" not in build_signature.parameters
