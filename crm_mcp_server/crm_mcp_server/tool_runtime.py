"""Runtime registry for stdio CRM report assistant tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from crm_mcp_server.report_context import (
    collect_presales_weekly_context,
    collect_sales_daily_context,
    collect_sales_weekly_context,
    sanitize_transport_detail,
)
from crm_mcp_server.report_drafts import (
    generate_presales_weekly_table,
    generate_sales_daily_draft,
    generate_sales_weekly_draft,
)
from crm_mcp_server.report_write import (
    create_report_after_confirmation,
    prepare_create_report_confirmation,
)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, object]


ToolHandler = Callable[[Mapping[str, object]], dict[str, object]]

_JSON_SCALAR_INPUT_SCHEMAS: tuple[dict[str, str], ...] = (
    {"type": "array"},
    {"type": "string"},
    {"type": "number"},
    {"type": "integer"},
    {"type": "boolean"},
    {"type": "null"},
)


def _permissive_input_schema(properties: dict[str, dict[str, str]]) -> dict[str, object]:
    return {
        "anyOf": [
            {"type": "object", "properties": properties},
            *_JSON_SCALAR_INPUT_SCHEMAS,
        ]
    }


_CONTEXT_INPUT_SCHEMA: dict[str, object] = _permissive_input_schema(
    {
        "window": {"description": "Report time window. Runtime handlers sanitize non-object values."},
        "scope": {"description": "CRM scope filters. Runtime handlers sanitize non-object values."},
        "options": {"description": "Optional collection limits. Runtime handlers sanitize non-object values."},
    }
)
_DRAFT_INPUT_SCHEMA: dict[str, object] = _permissive_input_schema(
    {"context": {"description": "Sanitized context. Runtime handlers sanitize non-object values."}}
)
_WRITE_INPUT_SCHEMA: dict[str, object] = _permissive_input_schema(
    {
        "draft": {"description": "Draft content for confirmation. Runtime handlers sanitize non-object values."},
        "report_type": {"description": "Report type. Runtime handlers sanitize non-string values."},
        "target": {"description": "Report target date or identifier. Runtime handlers sanitize non-string values."},
        "to": {"description": "Recipients. Runtime handlers keep only string list entries."},
        "confirmation_package": {"description": "Confirmation package. Runtime handlers sanitize non-object values."},
        "confirmation_text": {"description": "Explicit confirmation text. Runtime handlers sanitize non-string values."},
    }
)

_TOOL_DEFINITIONS = (
    ToolDefinition(
        name="crm_collect_sales_daily_context",
        description="Collect sanitized CRM context for a sales daily report.",
        input_schema=_CONTEXT_INPUT_SCHEMA,
    ),
    ToolDefinition(
        name="crm_collect_sales_weekly_context",
        description="Collect sanitized CRM context for a sales weekly report.",
        input_schema=_CONTEXT_INPUT_SCHEMA,
    ),
    ToolDefinition(
        name="crm_collect_presales_weekly_context",
        description="Collect sanitized CRM context for a presales weekly table.",
        input_schema=_CONTEXT_INPUT_SCHEMA,
    ),
    ToolDefinition(
        name="crm_generate_sales_daily_draft",
        description="Generate a sales daily report draft from sanitized context.",
        input_schema=_DRAFT_INPUT_SCHEMA,
    ),
    ToolDefinition(
        name="crm_generate_sales_weekly_draft",
        description="Generate a sales weekly report draft from sanitized context.",
        input_schema=_DRAFT_INPUT_SCHEMA,
    ),
    ToolDefinition(
        name="crm_generate_presales_weekly_table",
        description="Generate a presales weekly report table from sanitized context.",
        input_schema=_DRAFT_INPUT_SCHEMA,
    ),
    ToolDefinition(
        name="crm_create_report_after_confirmation",
        description="Create a CRM report after explicit confirmation.",
        input_schema=_WRITE_INPUT_SCHEMA,
    ),
)


def list_tool_definitions() -> tuple[ToolDefinition, ...]:
    return _TOOL_DEFINITIONS


def call_tool(name: str, arguments: Mapping[str, object] | None = None) -> dict[str, object]:
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return {"status": "ERROR", "reason": "unknown_tool"}
    return handler(arguments if isinstance(arguments, Mapping) else {})


def _collect_sales_daily(arguments: Mapping[str, object]) -> dict[str, object]:
    return collect_sales_daily_context(
        window=_mapping_argument(arguments, "window"),
        scope=_mapping_argument(arguments, "scope"),
        options=_mapping_argument(arguments, "options"),
        readers=_mock_readers(),
    )


def _collect_sales_weekly(arguments: Mapping[str, object]) -> dict[str, object]:
    return collect_sales_weekly_context(
        window=_mapping_argument(arguments, "window"),
        scope=_mapping_argument(arguments, "scope"),
        options=_mapping_argument(arguments, "options"),
        readers=_mock_readers(),
    )


def _collect_presales_weekly(arguments: Mapping[str, object]) -> dict[str, object]:
    return collect_presales_weekly_context(
        window=_mapping_argument(arguments, "window"),
        scope=_mapping_argument(arguments, "scope"),
        options=_mapping_argument(arguments, "options"),
        readers=_mock_readers(),
    )


def _generate_sales_daily(arguments: Mapping[str, object]) -> dict[str, object]:
    return generate_sales_daily_draft(_context_or_mock(arguments, "sales_daily"))


def _generate_sales_weekly(arguments: Mapping[str, object]) -> dict[str, object]:
    return generate_sales_weekly_draft(_context_or_mock(arguments, "sales_weekly"))


def _generate_presales_weekly(arguments: Mapping[str, object]) -> dict[str, object]:
    return generate_presales_weekly_table(_context_or_mock(arguments, "presales_weekly"))


def _create_report_after_confirmation(arguments: Mapping[str, object]) -> dict[str, object]:
    confirmation_package = _mapping_argument(arguments, "confirmation_package")
    confirmation_text = arguments.get("confirmation_text")
    if not confirmation_package:
        return prepare_create_report_confirmation(
            draft=_mapping_argument(arguments, "draft"),
            report_type=_report_type_argument(arguments.get("report_type")),
            target=_target_argument(arguments.get("target")),
            to=_string_list(arguments.get("to", [])),
        )

    return create_report_after_confirmation(
        confirmation_package=confirmation_package,
        confirmation_text=confirmation_text if isinstance(confirmation_text, str) else "",
        transport=MockReportWriteTransport(),
    )


class MockReportWriteTransport:
    auth_mode = "mock"
    http_status_category = "success"
    status_code_category = "2xx"
    transport_error_category = None

    def execute(self, operation_name: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        return {
            "data": {
                "createReport": {
                    "id": "mock-report-1",
                    "type": variables.get("type"),
                    "target": variables.get("target"),
                }
            }
        }


def _mapping_argument(arguments: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = arguments.get(key)
    return value if isinstance(value, Mapping) else {}


def _context_or_mock(arguments: Mapping[str, object], context_type: str) -> Mapping[str, object]:
    if "context" in arguments:
        return _mapping_argument(arguments, "context")

    window = {"start": "2026-05-04", "end": "2026-05-10"}
    if context_type == "sales_daily":
        return collect_sales_daily_context(
            window={"start": "2026-05-09", "end": "2026-05-09"},
            scope={"scope_id": "sales-user-1"},
            options={},
            readers=_mock_readers(),
        )
    if context_type == "sales_weekly":
        return collect_sales_weekly_context(
            window=window,
            scope={"scope_id": "sales-user-1"},
            options={},
            readers=_mock_readers(),
        )
    return collect_presales_weekly_context(
        window=window,
        scope={"scope_id": "presales-group-1"},
        options={},
        readers=_mock_readers(),
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [safe_item for item in value if (safe_item := _safe_text(item))]


def _report_type_argument(value: object) -> str:
    return value if isinstance(value, str) and value in {"daily", "weekly"} else "daily"


def _target_argument(value: object) -> str:
    return _safe_text(value)


def _safe_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    sanitized = sanitize_transport_detail(value)
    return sanitized.strip() if isinstance(sanitized, str) else ""


def _mock_readers() -> dict[str, Callable[[dict[str, object]], Mapping[str, object]]]:
    return {
        "reports": _mock_reports,
        "report_related_info": _mock_empty("report_related_info"),
        "projects": _mock_projects,
        "activities": _mock_activities,
        "leads": _mock_leads,
        "lead_pool": _mock_empty("lead_pool"),
        "scenarios": _mock_empty("scenarios"),
        "immediately_sign_projects": _mock_empty("immediately_sign_projects"),
    }


def _mock_reports(request: dict[str, object]) -> Mapping[str, object]:
    return _reader_result(
        source="reports",
        records=[
            {
                "id": "report-1",
                "title": "Previous Sales Daily",
                "summary": "Followed up renewal risks and next action owners.",
            }
        ],
    )


def _mock_projects(request: dict[str, object]) -> Mapping[str, object]:
    return _reader_result(
        source="projects",
        records=[
            {
                "id": "project-1",
                "title": "Customer A Renewal",
                "summary": "Renewal evaluation is active with procurement review pending.",
                "owner_id": "sales-user-1",
            }
        ],
    )


def _mock_activities(request: dict[str, object]) -> Mapping[str, object]:
    return _reader_result(
        source="activities",
        records=[
            {
                "id": "activity-1",
                "title": "Customer A renewal call",
                "summary": "Confirmed timeline and decision process.",
            }
        ],
    )


def _mock_leads(request: dict[str, object]) -> Mapping[str, object]:
    return _reader_result(
        source="leads",
        records=[
            {
                "id": "lead-1",
                "title": "Customer B Expansion",
                "summary": "Qualification requires budget owner confirmation.",
            }
        ],
    )


def _mock_empty(source: str) -> Callable[[dict[str, object]], Mapping[str, object]]:
    def reader(request: dict[str, object]) -> Mapping[str, object]:
        return _reader_result(source=source, records=[])

    return reader


def _reader_result(*, source: str, records: list[dict[str, object]]) -> Mapping[str, object]:
    return {
        "records": records,
        "source_refs": [
            {
                "id": f"mock-{source}",
                "system": "mock_crm",
                "query": source,
                "entity_type": source,
                "source_id": "mock",
                "fields": ["id", "title", "summary"],
            }
        ],
        "errors": [],
    }


_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "crm_collect_sales_daily_context": _collect_sales_daily,
    "crm_collect_sales_weekly_context": _collect_sales_weekly,
    "crm_collect_presales_weekly_context": _collect_presales_weekly,
    "crm_generate_sales_daily_draft": _generate_sales_daily,
    "crm_generate_sales_weekly_draft": _generate_sales_weekly,
    "crm_generate_presales_weekly_table": _generate_presales_weekly,
    "crm_create_report_after_confirmation": _create_report_after_confirmation,
}
