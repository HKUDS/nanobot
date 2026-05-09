"""Draft generation from sanitized CRM report context."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from crm_mcp_server.report_context import _sanitize_transport_detail

SUMMARY_SOURCES = (
    "reports",
    "projects",
    "activities",
    "leads",
    "lead_pool",
    "scenarios",
    "immediately_sign_projects",
)
TABLE_SOURCES = ("projects", "leads", "lead_pool", "scenarios", "activities")


def generate_sales_daily_draft(context: Mapping[str, object]) -> dict[str, object]:
    lines = ["Sales daily draft", "", *list(_summary_lines(context)), *list(_unavailable_source_lines(context))]
    return _draft("sales_daily", lines)


def generate_sales_weekly_draft(context: Mapping[str, object]) -> dict[str, object]:
    lines = [
        "本周工作总结",
        *list(_summary_lines(context)),
        "",
        "下周计划",
        "- Confirm next-week priorities and support needs from available CRM context before sending.",
        *list(_unavailable_source_lines(context)),
    ]
    return _draft("sales_weekly", lines)


def generate_presales_weekly_table(context: Mapping[str, object]) -> dict[str, object]:
    lines = [
        "| Sales | Source | Project/Lead/Scenario | Summary |",
        "| --- | --- | --- | --- |",
        *list(_table_rows(context)),
        *list(_unavailable_source_lines(context)),
    ]
    return _draft("presales_weekly_table", lines)


def _draft(draft_type: str, lines: Iterable[str]) -> dict[str, object]:
    return {
        "draft_type": draft_type,
        "content": "\n".join(line for line in lines if line),
        "requires_confirmation": True,
        "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
    }


def _summary_lines(context: Mapping[str, object]) -> Iterable[str]:
    records = _records(context)
    for source in SUMMARY_SOURCES:
        for record in _record_list(records.get(source)):
            title = _safe_text(record.get("title")) or _safe_text(record.get("id"))
            summary = _safe_text(record.get("summary"))
            if title and summary:
                yield f"- {source}: {title} - {summary}"
            elif title:
                yield f"- {source}: {title}"


def _table_rows(context: Mapping[str, object]) -> Iterable[str]:
    records = _records(context)
    sales = _sales_name(context)
    for source in TABLE_SOURCES:
        for record in _record_list(records.get(source)):
            title = _safe_text(record.get("title")) or _safe_text(record.get("id"))
            summary = _safe_text(record.get("summary"))
            if title:
                yield f"| {sales} | {source} | {title} | {summary} |"


def _unavailable_source_lines(context: Mapping[str, object]) -> Iterable[str]:
    unavailable_sources = context.get("unavailable_sources")
    if not isinstance(unavailable_sources, list):
        return
    for item in unavailable_sources:
        if not isinstance(item, Mapping):
            continue
        source = _safe_text(item.get("source"))
        if source == "business_chances":
            yield "Business chance data unavailable; do not infer partner opportunity facts."
        elif source:
            yield f"{source} data unavailable."


def _records(context: Mapping[str, object]) -> Mapping[str, object]:
    records = context.get("records")
    return records if isinstance(records, Mapping) else {}


def _record_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _sales_name(context: Mapping[str, object]) -> str:
    scope = context.get("scope")
    if not isinstance(scope, Mapping):
        return ""
    return _safe_text(scope.get("scope_id"))


def _safe_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    sanitized = _sanitize_transport_detail(value)
    if not isinstance(sanitized, str):
        return ""
    return sanitized.replace("|", "\\|").replace("\n", " ").strip()
