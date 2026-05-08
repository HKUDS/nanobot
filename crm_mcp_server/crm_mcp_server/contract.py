"""Static v1 read-only contracts for the CRM MCP server."""

from __future__ import annotations

V1_READ_ONLY_TOOL_NAMES: tuple[str, ...] = (
    "crm_generate_daily_report_facts",
    "crm_generate_weekly_report_facts",
    "crm_generate_dashboard_facts",
    "crm_check_read_boundary",
    "crm_smoke_check",
    "crm_list_projects",
)

V1_ALLOWED_QUERY_NAMES: tuple[str, ...] = (
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


def list_v1_tools() -> tuple[str, ...]:
    """Return the v1 read-only MCP tool names exposed by the skeleton."""

    return V1_READ_ONLY_TOOL_NAMES


def list_v1_query_names() -> tuple[str, ...]:
    """Return the canonical v1 read-only GraphQL query allow-list."""

    return V1_ALLOWED_QUERY_NAMES
