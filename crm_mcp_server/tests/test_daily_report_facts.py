from __future__ import annotations

import json

import pytest

SENSITIVE_MARKERS = (
    "raw GraphQL request",
    "raw GraphQL response",
    "endpoint",
    "tok" + "en",
    "Author" + "ization",
    "Bear" + "er",
    "Synthetic Project Name",
    "Synthetic Customer Name",
    "amount",
    "phone",
    "email",
    "contact",
    "address",
    "free-text CRM note",
)

DAILY_DIAGNOSTIC_ALLOWED_KEYS = {
    "status",
    "reason",
    "read_only",
    "mutations_allowed",
    "mutation_used",
    "dependency_tools",
    "project_records_count",
    "business_chance_records_count",
    "metrics_count",
    "unavailable_metrics_count",
}


class Reader:
    def __init__(self, result: dict[str, object]):
        self.result = result
        self.calls: list[dict[str, object]] = []

    def __call__(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(request)
        return self.result


def valid_window() -> dict[str, object]:
    return {"start": "2026-05-08", "end": "2026-05-08"}


def valid_scope() -> dict[str, object]:
    return {"scope_id": "team-a", "owner_ids": ["owner-1"], "group_ids": []}


def project_read_result() -> dict[str, object]:
    return {
        "records": [
            {"id": "project-1", "source_ref_ids": ["src-project-1"]},
            {"id": "project-2", "source_ref_ids": ["src-project-2"]},
        ],
        "source_refs": [
            source_ref("src-project-1", "Project", "project-1", "listProject"),
            source_ref("src-project-2", "Project", "project-2", "listProject"),
        ],
        "errors": [],
        "diagnostics": {"status": "OK"},
        "ignored_raw_payload": "raw GraphQL response Synthetic Project Name token",
    }


def business_chance_read_result() -> dict[str, object]:
    return {
        "records": [
            business_chance_record(
                "chance-1",
                status="open",
                apply_status="approved",
                due_at="2026-05-08T09:00:00Z",
                source_ref_id="src-chance-1",
            ),
            business_chance_record(
                "chance-2",
                status="open",
                apply_status="pending",
                due_at="2026-05-07T09:00:00Z",
                source_ref_id="src-shared",
            ),
            business_chance_record(
                "chance-3",
                status="won",
                apply_status="approved",
                due_at="2026-05-06T09:00:00Z",
                source_ref_id="src-shared",
            ),
        ],
        "source_refs": [
            source_ref("src-chance-1", "BusinessChance", "chance-1", "list_business_chance"),
            source_ref("src-shared", "BusinessChance", "chance-2", "list_business_chance"),
            source_ref("src-shared", "BusinessChance", "chance-2", "list_business_chance"),
        ],
        "errors": [],
        "diagnostics": {"status": "OK"},
        "ignored_raw_payload": "raw GraphQL request Synthetic Customer Name amount phone email",
    }


def business_chance_record(
    chance_id: str,
    *,
    status: str,
    apply_status: str,
    due_at: str,
    source_ref_id: str,
) -> dict[str, object]:
    return {
        "id": chance_id,
        "status": status,
        "apply_status": apply_status,
        "due_at": due_at,
        "source_ref_ids": [source_ref_id],
        "project_name": "Synthetic Project Name",
        "company_name": "Synthetic Customer Name",
        "amount": "10000",
        "phone": "phone",
        "email": "email",
        "contact": "contact",
        "address": "address",
        "note": "free-text CRM note",
    }


def source_ref(source_ref_id: str, entity_type: str, source_id: str, query: str) -> dict[str, object]:
    return {
        "id": source_ref_id,
        "system": "crm-graphql",
        "query": query,
        "entity_type": entity_type,
        "source_id": source_id,
        "fields": ["id"],
    }


def metric_by_name(result: dict[str, object], name: str) -> dict[str, object]:
    return next(metric for metric in result["metrics"] if metric["name"] == name)


def expected_error(category: str, message: str) -> dict[str, object]:
    return {"category": category, "message": message, "retryable": False}


def test_crm_generate_daily_report_facts_tool_name_is_exposed_as_read_only():
    from crm_mcp_server.contract import list_v1_tools
    from crm_mcp_server.server import get_server_metadata

    assert "crm_generate_daily_report_facts" in list_v1_tools()
    tool = next(
        tool
        for tool in get_server_metadata()["tools"]
        if tool["name"] == "crm_generate_daily_report_facts"
    )
    assert tool["read_only"] is True


@pytest.mark.parametrize(
    ("window", "reason"),
    [
        ({"end": "2026-05-08"}, "missing_window_start"),
        ({"start": "2026-05-08"}, "missing_window_end"),
        ({"start": "2026-05-07", "end": "2026-05-08"}, "non_daily_window"),
    ],
)
def test_rejects_non_daily_window_before_dependency_calls(
    window: dict[str, object], reason: str
):
    from crm_mcp_server.daily_report import crm_generate_daily_report_facts

    project_reader = Reader(project_read_result())
    business_chance_reader = Reader(business_chance_read_result())

    result = crm_generate_daily_report_facts(
        window=window,
        scope=valid_scope(),
        project_reader=project_reader,
        business_chance_reader=business_chance_reader,
    )

    assert project_reader.calls == []
    assert business_chance_reader.calls == []
    assert result["metrics"] == []
    assert result["unavailable_metrics"] == []
    assert result["source_refs"] == []
    assert result["errors"] == [expected_error("invalid_request", "The request is invalid.")]
    assert result["diagnostics"]["status"] == "ERROR"
    assert result["diagnostics"]["reason"] == reason
    assert result["diagnostics"]["mutation_used"] is False
    assert set(result["diagnostics"]) == DAILY_DIAGNOSTIC_ALLOWED_KEYS


def test_rejects_missing_scope_before_dependency_calls():
    from crm_mcp_server.daily_report import crm_generate_daily_report_facts

    project_reader = Reader(project_read_result())
    business_chance_reader = Reader(business_chance_read_result())

    result = crm_generate_daily_report_facts(
        window=valid_window(),
        scope={"owner_ids": ["owner-1"]},
        project_reader=project_reader,
        business_chance_reader=business_chance_reader,
    )

    assert project_reader.calls == []
    assert business_chance_reader.calls == []
    assert result["errors"] == [expected_error("invalid_request", "The request is invalid.")]
    assert result["diagnostics"]["reason"] == "missing_scope_id"
    assert result["diagnostics"]["mutation_used"] is False


def test_happy_path_returns_daily_report_shape_metrics_source_refs_and_diagnostics():
    from crm_mcp_server.daily_report import crm_generate_daily_report_facts

    project_reader = Reader(project_read_result())
    business_chance_reader = Reader(business_chance_read_result())


    result = crm_generate_daily_report_facts(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 50, "include_source_refs": True},
        project_reader=project_reader,
        business_chance_reader=business_chance_reader,
    )

    expected_request = {
        "window": valid_window(),
        "scope": valid_scope(),
        "options": {"max_records": 50},
    }
    assert project_reader.calls == [expected_request]
    assert business_chance_reader.calls == [expected_request]
    assert result["report_type"] == "daily"
    assert result["window"] == valid_window()
    assert result["scope"] == valid_scope()
    assert result["errors"] == []
    assert result["unavailable_metrics"] == []
    assert result["diagnostics"] == {
        "status": "OK",
        "reason": "ok",
        "read_only": True,
        "mutations_allowed": False,
        "mutation_used": False,
        "dependency_tools": ["crm_list_projects", "crm_list_business_chances"],
        "project_records_count": 2,
        "business_chance_records_count": 3,
        "metrics_count": 6,
        "unavailable_metrics_count": 0,
    }
    assert set(result["diagnostics"]) == DAILY_DIAGNOSTIC_ALLOWED_KEYS
    assert_no_sensitive_output(result)


def test_computes_project_count():
    result = generate_happy_report()

    assert metric_by_name(result, "project_count") == {
        "name": "project_count",
        "value": 2,
        "unit": "count",
        "window": valid_window(),
        "scope_id": "team-a",
        "source_ref_ids": ["src-project-1", "src-project-2"],
    }


def test_computes_business_chance_count():
    result = generate_happy_report()

    assert metric_by_name(result, "business_chance_count") == {
        "name": "business_chance_count",
        "value": 3,
        "unit": "count",
        "window": valid_window(),
        "scope_id": "team-a",
        "source_ref_ids": ["src-chance-1", "src-shared"],
    }


def test_computes_business_chance_status_distribution():
    result = generate_happy_report()

    assert metric_by_name(result, "business_chance_status_distribution") == {
        "name": "business_chance_status_distribution",
        "value": {"open": 2, "won": 1},
        "unit": "count_by_status",
        "window": valid_window(),
        "scope_id": "team-a",
        "source_ref_ids": ["src-chance-1", "src-shared"],
    }


def test_computes_business_chance_apply_status_distribution():
    result = generate_happy_report()

    assert metric_by_name(result, "business_chance_apply_status_distribution") == {
        "name": "business_chance_apply_status_distribution",
        "value": {"approved": 2, "pending": 1},
        "unit": "count_by_apply_status",
        "window": valid_window(),
        "scope_id": "team-a",
        "source_ref_ids": ["src-chance-1", "src-shared"],
    }


def test_computes_business_chance_due_today_count():
    result = generate_happy_report()

    assert metric_by_name(result, "business_chance_due_today_count") == {
        "name": "business_chance_due_today_count",
        "value": 1,
        "unit": "count",
        "window": valid_window(),
        "scope_id": "team-a",
        "source_ref_ids": ["src-chance-1"],
    }


def test_computes_business_chance_overdue_count():
    result = generate_happy_report()

    assert metric_by_name(result, "business_chance_overdue_count") == {
        "name": "business_chance_overdue_count",
        "value": 1,
        "unit": "count",
        "window": valid_window(),
        "scope_id": "team-a",
        "source_ref_ids": ["src-shared"],
    }


def test_merges_and_deduplicates_source_refs():
    result = generate_happy_report()

    assert result["source_refs"] == [
        source_ref("src-project-1", "Project", "project-1", "listProject"),
        source_ref("src-project-2", "Project", "project-2", "listProject"),
        source_ref("src-chance-1", "BusinessChance", "chance-1", "list_business_chance"),
        source_ref("src-shared", "BusinessChance", "chance-2", "list_business_chance"),
    ]


def test_honors_include_source_refs_false():
    from crm_mcp_server.daily_report import crm_generate_daily_report_facts

    result = crm_generate_daily_report_facts(
        window=valid_window(),
        scope=valid_scope(),
        options={"include_source_refs": False},
        project_reader=Reader(project_read_result()),
        business_chance_reader=Reader(business_chance_read_result()),
    )

    assert result["source_refs"] == []
    assert all(metric["source_ref_ids"] == [] for metric in result["metrics"])


def test_honors_include_unavailable_metrics_false():
    from crm_mcp_server.daily_report import crm_generate_daily_report_facts

    result = crm_generate_daily_report_facts(
        window=valid_window(),
        scope=valid_scope(),
        options={"include_unavailable_metrics": False},
        project_reader=Reader(error_result()),
        business_chance_reader=Reader(error_result()),
    )

    assert result["metrics"] == []
    assert result["unavailable_metrics"] == []
    assert result["diagnostics"]["status"] == "INCONCLUSIVE"
    assert result["diagnostics"]["reason"] == "dependency_error"
    assert result["diagnostics"]["unavailable_metrics_count"] == 0
    assert_no_sensitive_output(result)


def test_dependency_error_creates_unavailable_metrics_without_inferred_values():
    from crm_mcp_server.daily_report import crm_generate_daily_report_facts

    result = crm_generate_daily_report_facts(
        window=valid_window(),
        scope=valid_scope(),
        project_reader=Reader(error_result()),
        business_chance_reader=Reader(error_result()),
    )

    assert result["metrics"] == []
    assert result["source_refs"] == []
    assert result["errors"] == []
    assert result["unavailable_metrics"] == [
        {
            "name": "project_count",
            "missing_inputs": ["crm_list_projects.records"],
            "reason": "dependency_error",
        },
        {
            "name": "business_chance_count",
            "missing_inputs": ["crm_list_business_chances.records"],
            "reason": "dependency_error",
        },
        {
            "name": "business_chance_status_distribution",
            "missing_inputs": ["crm_list_business_chances.records"],
            "reason": "dependency_error",
        },
        {
            "name": "business_chance_apply_status_distribution",
            "missing_inputs": ["crm_list_business_chances.records"],
            "reason": "dependency_error",
        },
        {
            "name": "business_chance_due_today_count",
            "missing_inputs": ["crm_list_business_chances.records"],
            "reason": "dependency_error",
        },
        {
            "name": "business_chance_overdue_count",
            "missing_inputs": ["crm_list_business_chances.records"],
            "reason": "dependency_error",
        },
    ]
    assert result["diagnostics"]["status"] == "INCONCLUSIVE"
    assert result["diagnostics"]["reason"] == "dependency_error"
    assert result["diagnostics"]["metrics_count"] == 0
    assert result["diagnostics"]["unavailable_metrics_count"] == 6
    assert_no_sensitive_output(result)


def test_mutation_used_is_false_and_write_like_tools_remain_hidden():
    from crm_mcp_server.contract import list_v1_tools

    result = generate_happy_report()

    assert result["diagnostics"]["mutation_used"] is False
    for tool_name in list_v1_tools():
        assert "create" not in tool_name
        assert "update" not in tool_name
        assert "delete" not in tool_name
        assert "mutation" not in tool_name


def generate_happy_report() -> dict[str, object]:
    from crm_mcp_server.daily_report import crm_generate_daily_report_facts

    return crm_generate_daily_report_facts(
        window=valid_window(),
        scope=valid_scope(),
        project_reader=Reader(project_read_result()),
        business_chance_reader=Reader(business_chance_read_result()),
    )


def error_result() -> dict[str, object]:
    return {
        "records": [],
        "source_refs": [],
        "errors": [expected_error("graphql_error", "The CRM query returned an error.")],
        "diagnostics": {"status": "ERROR", "reason": "graphql_error"},
        "raw_error": "raw GraphQL response Synthetic Customer Name token",
    }


def assert_no_sensitive_output(result: dict[str, object]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized
