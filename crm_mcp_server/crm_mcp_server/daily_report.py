"""Sanitized daily report facts composed from mocked CRM MCP read-tool outputs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Mapping

from crm_mcp_server.business_chances import MAX_RECORDS_CAP
from crm_mcp_server.redaction import sanitize_errors

Reader = Callable[[dict[str, object]], Mapping[str, object]]

DEPENDENCY_TOOLS = ["crm_list_projects", "crm_list_business_chances"]
TERMINAL_BUSINESS_CHANCE_STATUSES = {"won", "lost", "closed"}
PROJECT_METRICS = ("project_count",)
BUSINESS_CHANCE_METRICS = (
    "business_chance_count",
    "business_chance_status_distribution",
    "business_chance_apply_status_distribution",
    "business_chance_due_today_count",
    "business_chance_overdue_count",
)


def crm_generate_daily_report_facts(
    *,
    window: Mapping[str, object],
    scope: Mapping[str, object],
    options: Mapping[str, object] | None = None,
    project_reader: Reader | None = None,
    business_chance_reader: Reader | None = None,
) -> dict[str, object]:
    """Return sanitized daily report facts from mocked read-tool outputs."""

    safe_options = options if isinstance(options, Mapping) else {}
    validation_reason = _validate_request(window, scope, safe_options)
    if validation_reason is not None:
        return _result(
            window=window,
            scope=scope,
            metrics=[],
            unavailable_metrics=[],
            source_refs=[],
            errors=["invalid_request"],
            diagnostics=_diagnostics(status="ERROR", reason=validation_reason),
        )

    safe_window = _safe_window(window)
    safe_scope = _safe_scope(scope)
    read_request = {
        "window": safe_window,
        "scope": safe_scope,
        "options": {"max_records": _requested_max_records(safe_options)},
    }
    project_result = _call_reader(project_reader, read_request)
    business_chance_result = _call_reader(business_chance_reader, read_request)

    include_source_refs = safe_options.get("include_source_refs", True) is not False
    include_unavailable_metrics = safe_options.get("include_unavailable_metrics", True) is not False
    project_dependency_ok = not project_result.get("errors")
    business_dependency_ok = not business_chance_result.get("errors")
    project_records = _records(project_result) if project_dependency_ok else []
    business_chance_records = _records(business_chance_result) if business_dependency_ok else []

    metrics: list[dict[str, object]] = []
    unavailable_metrics: list[dict[str, object]] = []
    if project_dependency_ok:
        metrics.append(
            _metric(
                name="project_count",
                value=len(project_records),
                unit="count",
                window=safe_window,
                scope_id=safe_scope["scope_id"],
                source_ref_ids=_record_source_ref_ids(project_records, include_source_refs),
            )
        )
    elif include_unavailable_metrics:
        unavailable_metrics.extend(_unavailable_metrics(PROJECT_METRICS, "crm_list_projects.records"))

    if business_dependency_ok:
        business_source_ref_ids = _record_source_ref_ids(business_chance_records, include_source_refs)
        due_today_ref_ids = _business_chance_due_today_ref_ids(
            business_chance_records, str(safe_window["start"]), include_source_refs
        )
        overdue_ref_ids = _business_chance_overdue_ref_ids(
            business_chance_records, str(safe_window["start"]), include_source_refs
        )
        metrics.extend(
            [
                _metric(
                    name="business_chance_count",
                    value=len(business_chance_records),
                    unit="count",
                    window=safe_window,
                    scope_id=safe_scope["scope_id"],
                    source_ref_ids=business_source_ref_ids,
                ),
                _metric(
                    name="business_chance_status_distribution",
                    value=_distribution(business_chance_records, "status"),
                    unit="count_by_status",
                    window=safe_window,
                    scope_id=safe_scope["scope_id"],
                    source_ref_ids=business_source_ref_ids,
                ),
                _metric(
                    name="business_chance_apply_status_distribution",
                    value=_distribution(business_chance_records, "apply_status"),
                    unit="count_by_apply_status",
                    window=safe_window,
                    scope_id=safe_scope["scope_id"],
                    source_ref_ids=business_source_ref_ids,
                ),
                _metric(
                    name="business_chance_due_today_count",
                    value=len(due_today_ref_ids) if include_source_refs else _due_today_count(business_chance_records, str(safe_window["start"])),
                    unit="count",
                    window=safe_window,
                    scope_id=safe_scope["scope_id"],
                    source_ref_ids=due_today_ref_ids,
                ),
                _metric(
                    name="business_chance_overdue_count",
                    value=len(overdue_ref_ids) if include_source_refs else _overdue_count(business_chance_records, str(safe_window["start"])),
                    unit="count",
                    window=safe_window,
                    scope_id=safe_scope["scope_id"],
                    source_ref_ids=overdue_ref_ids,
                ),
            ]
        )
    elif include_unavailable_metrics:
        unavailable_metrics.extend(
            _unavailable_metrics(BUSINESS_CHANCE_METRICS, "crm_list_business_chances.records")
        )

    source_refs = []
    if include_source_refs and project_dependency_ok and business_dependency_ok:
        source_refs = _dedupe_source_refs(
            [*_source_refs(project_result), *_source_refs(business_chance_result)]
        )

    reason = "ok"
    status = "OK"
    if not project_dependency_ok or not business_dependency_ok:
        reason = "dependency_error"
        status = "INCONCLUSIVE"

    return _result(
        window=safe_window,
        scope=safe_scope,
        metrics=metrics,
        unavailable_metrics=unavailable_metrics,
        source_refs=source_refs,
        errors=[],
        diagnostics=_diagnostics(
            status=status,
            reason=reason,
            project_records_count=len(project_records),
            business_chance_records_count=len(business_chance_records),
            metrics_count=len(metrics),
            unavailable_metrics_count=len(unavailable_metrics),
        ),
    )


def _validate_request(
    window: Mapping[str, object], scope: Mapping[str, object], options: Mapping[str, object]
) -> str | None:
    if not isinstance(window, Mapping) or not window.get("start"):
        return "missing_window_start"
    if not window.get("end"):
        return "missing_window_end"
    if window["start"] != window["end"]:
        return "non_daily_window"
    if not isinstance(scope, Mapping) or not scope.get("scope_id"):
        return "missing_scope_id"
    max_records = _requested_max_records(options)
    if max_records <= 0:
        return "invalid_max_records"
    if max_records > MAX_RECORDS_CAP:
        return "max_records_exceeds_cap"
    return None


def _requested_max_records(options: Mapping[str, object]) -> int:
    value = options.get("max_records", 50)
    return value if isinstance(value, int) else 0


def _safe_window(window: Mapping[str, object]) -> dict[str, object]:
    return {"start": window["start"], "end": window["end"]}


def _safe_scope(scope: Mapping[str, object]) -> dict[str, object]:
    return {
        "scope_id": str(scope["scope_id"]),
        "owner_ids": _safe_string_list(scope.get("owner_ids")),
        "group_ids": _safe_string_list(scope.get("group_ids")),
    }


def _safe_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _call_reader(reader: Reader | None, read_request: dict[str, object]) -> Mapping[str, object]:
    if reader is None:
        return {"records": [], "source_refs": [], "errors": sanitize_errors(["config_missing"])}
    return reader(read_request)


def _records(result: Mapping[str, object]) -> list[Mapping[str, object]]:
    records = result.get("records")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, Mapping)]


def _source_refs(result: Mapping[str, object]) -> list[Mapping[str, object]]:
    source_refs = result.get("source_refs")
    if not isinstance(source_refs, list):
        return []
    return [source_ref for source_ref in source_refs if isinstance(source_ref, Mapping)]


def _record_source_ref_ids(records: list[Mapping[str, object]], include_source_refs: bool) -> list[str]:
    if not include_source_refs:
        return []
    source_ref_ids: list[str] = []
    for record in records:
        source_ref_ids.extend(_safe_string_list(record.get("source_ref_ids")))
    return _dedupe_strings(source_ref_ids)


def _distribution(records: list[Mapping[str, object]], field: str) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for record in records:
        value = record.get(field)
        if isinstance(value, str) and value:
            distribution[value] = distribution.get(value, 0) + 1
    return distribution


def _business_chance_due_today_ref_ids(
    records: list[Mapping[str, object]], report_date: str, include_source_refs: bool
) -> list[str]:
    return _record_source_ref_ids(
        [record for record in records if _date_part(record.get("due_at")) == report_date],
        include_source_refs,
    )


def _business_chance_overdue_ref_ids(
    records: list[Mapping[str, object]], report_date: str, include_source_refs: bool
) -> list[str]:
    return _record_source_ref_ids(
        [record for record in records if _is_overdue(record, report_date)],
        include_source_refs,
    )


def _due_today_count(records: list[Mapping[str, object]], report_date: str) -> int:
    return sum(1 for record in records if _date_part(record.get("due_at")) == report_date)


def _overdue_count(records: list[Mapping[str, object]], report_date: str) -> int:
    return sum(1 for record in records if _is_overdue(record, report_date))


def _is_overdue(record: Mapping[str, object], report_date: str) -> bool:
    status = record.get("status")
    if isinstance(status, str) and status.lower() in TERMINAL_BUSINESS_CHANCE_STATUSES:
        return False
    due_date = _date_part(record.get("due_at"))
    return bool(due_date and due_date < report_date)


def _date_part(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value[:10]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _dedupe_source_refs(source_refs: list[Mapping[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for source_ref in source_refs:
        source_ref_id = source_ref.get("id")
        if not isinstance(source_ref_id, str) or source_ref_id in seen:
            continue
        seen.add(source_ref_id)
        deduped.append(
            {
                "id": source_ref_id,
                "system": _safe_string(source_ref.get("system")),
                "query": _safe_string(source_ref.get("query")),
                "entity_type": _safe_string(source_ref.get("entity_type")),
                "source_id": _safe_string(source_ref.get("source_id")),
                "fields": _safe_string_list(source_ref.get("fields")),
            }
        )
    return deduped


def _safe_string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _metric(
    *,
    name: str,
    value: object,
    unit: str,
    window: dict[str, object],
    scope_id: object,
    source_ref_ids: list[str],
) -> dict[str, object]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "window": window,
        "scope_id": scope_id,
        "source_ref_ids": source_ref_ids,
    }


def _unavailable_metrics(metric_names: tuple[str, ...], missing_input: str) -> list[dict[str, object]]:
    return [
        {"name": name, "missing_inputs": [missing_input], "reason": "dependency_error"}
        for name in metric_names
    ]


def _diagnostics(
    *,
    status: str,
    reason: str,
    project_records_count: int = 0,
    business_chance_records_count: int = 0,
    metrics_count: int = 0,
    unavailable_metrics_count: int = 0,
) -> dict[str, object]:
    return {
        "status": status,
        "reason": reason,
        "read_only": True,
        "mutations_allowed": False,
        "mutation_used": False,
        "dependency_tools": DEPENDENCY_TOOLS,
        "project_records_count": project_records_count,
        "business_chance_records_count": business_chance_records_count,
        "metrics_count": metrics_count,
        "unavailable_metrics_count": unavailable_metrics_count,
    }


def _result(
    *,
    window: Mapping[str, object],
    scope: Mapping[str, object],
    metrics: list[dict[str, object]],
    unavailable_metrics: list[dict[str, object]],
    source_refs: list[dict[str, object]],
    errors: list[str],
    diagnostics: dict[str, object],
) -> dict[str, object]:
    return {
        "report_type": "daily",
        "window": dict(window),
        "scope": dict(scope),
        "metrics": metrics,
        "unavailable_metrics": unavailable_metrics,
        "source_refs": source_refs,
        "errors": sanitize_errors(errors),
        "diagnostics": diagnostics,
    }
