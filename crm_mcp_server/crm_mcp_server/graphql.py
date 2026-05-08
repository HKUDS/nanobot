"""Read-only GraphQL operation contract without transport execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from crm_mcp_server.contract import V1_ALLOWED_QUERY_NAMES


class GraphQLContractError(ValueError):
    """Raised when a GraphQL operation violates the CRM MCP read contract."""


@dataclass(frozen=True)
class ReadOperation:
    operation_name: str
    operation_type: str
    query: str
    variables: Mapping[str, Any]


WRITE_LIKE_NAME_FRAGMENTS: tuple[str, ...] = (
    "create",
    "update",
    "delete",
    "remove",
    "assign",
    "claim",
    "transfer",
    "review",
    "audit",
    "sync",
    "send",
    "contact",
    "message",
    "task",
    "export",
    "writeback",
)

_OPERATION_TOKEN_RE = re.compile(r"\bmutation\b", re.IGNORECASE)

_FIXED_SELECTION_SETS: Mapping[str, str] = MappingProxyType(
    {
        "listReport": """
            total
            skip
            limit
            data { id type target creator { id name } }
        """,
        "reportInfo": """
            id
            type
            target
            creator { id name }
            related_info { id type }
        """,
        "reportRelatedInfo": """
            projects { id name }
            companies { id name }
            business_chances { id project_name }
        """,
        "listProject": """
            total
            skip
            limit
            data { id name stage claimBy { user { id name } } created_at updated_at }
        """,
        "projectInfo": """
            id
            name
            stage
            claimBy { user { id name } }
            created_at
            updated_at
        """,
        "listActivity": """
            total
            skip
            limit
            data { id type domain creator { id name } created_at updated_at }
        """,
        "listCompany": """
            total
            skip
            limit
            data { id name rank claim_by { id name } claim_by_group { id name } created_at updated_at }
        """,
        "companyInfo": """
            id
            name
            rank
            claim_by { id name }
            claim_by_group { id name }
            created_at
            updated_at
        """,
        "listUser": """
            total
            skip
            limit
            data { id username name enabled }
        """,
        "list_business_chance": """
            total
            skip
            limit
            data { id project_name status apply_status claim_by { id name } due_at created_at updated_at }
        """,
        "business_chance": """
            id
            project_name
            status
            apply_status
            claim_by { id name }
            due_at
            created_at
            updated_at
        """,
    }
)


def build_read_operation(
    operation_name: str,
    *,
    variables: Mapping[str, Any] | None = None,
    operation_type: str = "query",
) -> ReadOperation:
    """Build an allow-listed read operation; do not execute transport."""

    _validate_read_contract(operation_name, operation_type)
    query = _build_fixed_query(operation_name)
    validate_read_query_text(query)
    return ReadOperation(
        operation_name=operation_name,
        operation_type="query",
        query=query,
        variables=dict(variables or {}),
    )


def _validate_read_contract(operation_name: str, operation_type: str) -> None:
    normalized_type = operation_type.strip().lower()
    if normalized_type != "query":
        raise GraphQLContractError("Mutation is forbidden by the v1 CRM MCP read contract")
    if _is_write_like_name(operation_name):
        raise GraphQLContractError("Write-like GraphQL operation names are forbidden")
    if operation_name not in V1_ALLOWED_QUERY_NAMES:
        raise GraphQLContractError(f"GraphQL operation {operation_name!r} is not allow-listed")


def validate_read_query_text(query_text: str) -> None:
    """Validate generated query text without exposing a transport passthrough."""

    if _OPERATION_TOKEN_RE.search(query_text):
        raise GraphQLContractError("Mutation is forbidden by the v1 CRM MCP read contract")


def _is_write_like_name(operation_name: str) -> bool:
    lower_name = operation_name.lower()
    return any(fragment in lower_name for fragment in WRITE_LIKE_NAME_FRAGMENTS)


def _build_fixed_query(operation_name: str) -> str:
    selection = _FIXED_SELECTION_SETS[operation_name].strip()
    return f"query {operation_name}($search: SearchParam, $id: ID) {{\n  {operation_name} {{\n{_indent(selection)}\n  }}\n}}"


def _indent(selection: str) -> str:
    return "\n".join(f"    {line.strip()}" for line in selection.splitlines() if line.strip())
