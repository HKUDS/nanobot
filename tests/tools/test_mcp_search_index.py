from unittest.mock import Mock

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp_search_index import McpSearchIndex


def _tool(name: str, description: str = "", **properties: object) -> Tool:
    tool = Mock(spec=Tool)
    tool.name = name
    tool.description = description
    tool.parameters = {"type": "object", "properties": properties}
    return tool


def test_name_match_outranks_description_without_filling_from_mcp_prefix() -> None:
    named = _tool("mcp_git_listHTTPHeaders")
    described = _tool("mcp_docs_lookup", "HTTP headers reference")
    index = McpSearchIndex([described, _tool("mcp_git_clone"), named])

    assert index.search("mcp HTTP headers") == [named.name, described.name]
    assert index.search("unknown") == []


def test_exact_registered_name_wins_over_equivalent_tokens() -> None:
    snake = _tool("mcp_repo_find_issues")
    camel = _tool("mcp_repo_findIssues")
    index = McpSearchIndex([camel, snake])

    assert index.search(snake.name, limit=1) == [snake.name]
    assert index.search(camel.name, limit=0) == []


def test_nested_parameter_names_and_descriptions_are_searchable() -> None:
    address = {"type": "object", "properties": {
        "postalCode": {"type": "string", "description": "Recipient zipcode"},
    }}
    tool = _tool("mcp_reports_run", filters={"type": "array", "items": address})
    index = McpSearchIndex([tool, _tool("mcp_reports_list")])

    assert index.search("postal code") == [tool.name]
    assert index.search("zipcode") == [tool.name]


def test_rare_term_outweighs_common_server_name_and_ties_are_stable() -> None:
    tools = [_tool(f"mcp_docs_{verb}") for verb in ("add", "get", "list", "put", "read")]
    ledger = _tool("mcp_bank_lookup", "Retrieve the ledger")
    expected = [ledger.name, "mcp_docs_add", "mcp_docs_get"]

    for catalog in ([*tools, ledger], [ledger, *reversed(tools)]):
        assert McpSearchIndex(catalog).search("docs ledger", limit=3) == expected
