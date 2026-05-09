"""Static v1 contracts for the CRM MCP server."""

from __future__ import annotations

V1_READ_ONLY_TOOL_NAMES: tuple[str, ...] = (
    "crm_collect_sales_daily_context",
    "crm_collect_sales_weekly_context",
    "crm_collect_presales_weekly_context",
    "crm_generate_sales_daily_draft",
    "crm_generate_sales_weekly_draft",
    "crm_generate_presales_weekly_table",
)

V1_CONFIRMATION_GATED_WRITE_TOOL_NAMES: tuple[str, ...] = (
    "crm_create_report_after_confirmation",
)

V1_ALLOWED_QUERY_NAMES: tuple[str, ...] = (
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

V1_CONFIRMATION_GATED_MUTATION_NAMES: tuple[str, ...] = (
    "createReport",
)


def list_v1_tools() -> tuple[str, ...]:
    """Return the v1 CRM MCP tool names exposed by the skeleton."""

    return (*V1_READ_ONLY_TOOL_NAMES, *V1_CONFIRMATION_GATED_WRITE_TOOL_NAMES)


def list_v1_read_only_tools() -> tuple[str, ...]:
    """Return v1 tool names that never write CRM state."""

    return V1_READ_ONLY_TOOL_NAMES


def list_v1_write_tools() -> tuple[str, ...]:
    """Return v1 tool names that may write after explicit confirmation."""

    return V1_CONFIRMATION_GATED_WRITE_TOOL_NAMES


def list_v1_query_names() -> tuple[str, ...]:
    """Return the canonical v1 read-only GraphQL query allow-list."""

    return V1_ALLOWED_QUERY_NAMES


def list_v1_mutation_names() -> tuple[str, ...]:
    """Return confirmation-gated mutation names allowed in v1."""

    return V1_CONFIRMATION_GATED_MUTATION_NAMES
