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


@dataclass(frozen=True)
class GraphQLOperation:
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
            data { id name stage claimBy { id user { name } } created_at updated_at }
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
        "list_leads": """
            total
            skip
            limit
            data { id name title created_at updated_at }
        """,
        "list_leads_pool": """
            total
            skip
            limit
            data { id name title created_at updated_at }
        """,
        "list_opportunity_scenario": """
            total
            skip
            limit
            data { id name title created_at updated_at }
        """,
        "listImmediatelySignProject": """
            id
            name
            project_name
            created_at
            updated_at
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

_FIXED_ARGUMENTS: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "listReport": MappingProxyType(
            {"search": "[ReportSearchParam!]", "pagination": "PaginationParam"}
        ),
        "reportInfo": MappingProxyType({"id": "ID!"}),
        "reportRelatedInfo": MappingProxyType(
            {"target": "Time!", "creator": "ID!", "type": "ReportType!"}
        ),
        "listProject": MappingProxyType(
            {
                "search": "ProjectSearchParam!",
                "pagination": "PaginationParam",
                "sort_by": "SortBy!",
            }
        ),
        "projectInfo": MappingProxyType({"id": "ID!"}),
        "listActivity": MappingProxyType(
            {"search": "[ActivitySearchParam!]", "pagination": "PaginationParam"}
        ),
        "listCompany": MappingProxyType(
            {"search": "[CompanySearchParam!]", "pagination": "PaginationParam"}
        ),
        "companyInfo": MappingProxyType({"id": "ID!"}),
        "listUser": MappingProxyType({"search": "UserSearchParam!", "pagination": "PaginationParam"}),
        "list_leads": MappingProxyType(
            {"search": "LeadsSearchParam", "pagination": "PaginationParam", "sort_by": "SortBy"}
        ),
        "list_leads_pool": MappingProxyType(
            {"search": "LeadsSearchParam", "pagination": "PaginationParam"}
        ),
        "list_opportunity_scenario": MappingProxyType(
            {
                "search": "OpportunityScenarioSearchParam!",
                "pagination": "PaginationParam",
                "sort_by": "SortBy!",
            }
        ),
        "list_business_chance": MappingProxyType(
            {"search": "BusinessChanceSearchParam", "pagination": "PaginationParam"}
        ),
        "business_chance": MappingProxyType({"id": "ID!"}),
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
    prepared_variables = _prepare_read_variables(operation_name, variables or {})
    query = _build_fixed_query(operation_name, prepared_variables)
    validate_read_query_text(query)
    return ReadOperation(
        operation_name=operation_name,
        operation_type="query",
        query=query,
        variables=prepared_variables,
    )


def build_create_report_mutation(
    *,
    content: str,
    report_type: str,
    target: str,
    to: list[str],
    attachments: list[str],
    project_infos: list[Mapping[str, Any]],
    immediately_sign_projects: list[Mapping[str, Any]],
) -> GraphQLOperation:
    """Build the only v1 write operation, gated by report_write confirmation."""

    if not content.strip():
        raise GraphQLContractError("Report content is required")
    if report_type not in {"daily", "weekly"}:
        raise GraphQLContractError("Report type must be daily or weekly")
    if not target:
        raise GraphQLContractError("Report target is required")
    query = """
mutation createReport(
  $content: String!,
  $type: ReportType!,
  $target: Time!,
  $to: [ID!],
  $attachments: [ID!],
  $project_infos: [InputProjectInfo!],
  $immediately_sign_projects: [InputCreateImmediatelySignProject!]
) {
  createReport(
    content: $content,
    type: $type,
    target: $target,
    to: $to,
    attachments: $attachments,
    project_infos: $project_infos,
    immediately_sign_projects: $immediately_sign_projects
  ) {
    id
    type
    target
  }
}
""".strip()
    return GraphQLOperation(
        operation_name="createReport",
        operation_type="mutation",
        query=query,
        variables={
            "content": content,
            "type": report_type,
            "target": target,
            "to": list(to),
            "attachments": list(attachments),
            "project_infos": [dict(item) for item in project_infos],
            "immediately_sign_projects": [dict(item) for item in immediately_sign_projects],
        },
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


def _build_fixed_query(operation_name: str, variables: Mapping[str, Any]) -> str:
    if operation_name == "listProjectID":
        return f"query {operation_name} {{\n  {operation_name}\n}}"
    selection = _FIXED_SELECTION_SETS[operation_name].strip()
    allowed_arguments = _FIXED_ARGUMENTS.get(operation_name, {})
    used_arguments = tuple(name for name in allowed_arguments if name in variables)
    operation_signature = _operation_signature(operation_name, used_arguments, allowed_arguments)
    field_arguments = _field_arguments(used_arguments)
    return (
        f"{operation_signature} {{\n"
        f"  {operation_name}{field_arguments} {{\n"
        f"{_indent(selection)}\n"
        "  }\n"
        "}"
    )


def _prepare_read_variables(operation_name: str, variables: Mapping[str, Any]) -> dict[str, Any]:
    allowed_arguments = _FIXED_ARGUMENTS.get(operation_name, {})
    return {name: variables[name] for name in allowed_arguments if name in variables}


def _operation_signature(
    operation_name: str,
    used_arguments: tuple[str, ...],
    allowed_arguments: Mapping[str, str],
) -> str:
    if not used_arguments:
        return f"query {operation_name}"
    declarations = ", ".join(f"${name}: {allowed_arguments[name]}" for name in used_arguments)
    return f"query {operation_name}({declarations})"


def _field_arguments(used_arguments: tuple[str, ...]) -> str:
    if not used_arguments:
        return ""
    bindings = ", ".join(f"{name}: ${name}" for name in used_arguments)
    return f"({bindings})"


def _indent(selection: str) -> str:
    return "\n".join(f"    {line.strip()}" for line in selection.splitlines() if line.strip())
