from __future__ import annotations

import json


def context() -> dict[str, object]:
    return {
        "context_type": "sales_daily",
        "window": {"start": "2026-05-08", "end": "2026-05-08"},
        "scope": {"scope_id": "sales-user-1", "owner_ids": ["sales-user-1"], "group_ids": []},
        "records": {
            "reports": [{"id": "report-1", "title": "Yesterday", "summary": "Followed Customer A"}],
            "report_related_info": [],
            "projects": [{"id": "project-1", "title": "Customer A Renewal", "summary": "Price discussion"}],
            "activities": [{"id": "activity-1", "title": "Dinner Visit", "summary": "Discussed next steps"}],
            "leads": [{"id": "lead-1", "title": "Scenario Lead", "summary": "Needs presales support"}],
            "lead_pool": [{"id": "pool-1", "title": "Pool Lead", "summary": "Can follow next week"}],
            "scenarios": [{"id": "scenario-1", "title": "Industry Scenario", "summary": "Coverage opportunity"}],
            "immediately_sign_projects": [],
        },
        "source_refs": [],
        "unavailable_sources": [{"source": "business_chances", "reason": "dependency_error"}],
        "diagnostics": {"status": "INCONCLUSIVE"},
    }


def test_generate_sales_daily_draft_keeps_internal_business_context():
    from crm_mcp_server.report_drafts import generate_sales_daily_draft

    result = generate_sales_daily_draft(context())

    content = result["content"]

    assert result["draft_type"] == "sales_daily"
    assert "Customer A Renewal" in content
    assert "Dinner Visit" in content
    assert "Scenario Lead" in content
    assert "Business chance data unavailable" in content
    assert result["requires_confirmation"] is True
    assert_no_transport_secrets(result)


def test_generate_sales_weekly_draft_has_next_week_plan_section():
    from crm_mcp_server.report_drafts import generate_sales_weekly_draft

    weekly_context = context()
    weekly_context["context_type"] = "sales_weekly"

    result = generate_sales_weekly_draft(weekly_context)

    content = result["content"]

    assert result["draft_type"] == "sales_weekly"
    assert "本周工作总结" in content
    assert "下周计划" in content
    assert "Customer A Renewal" in content
    assert "Confirm next-week priorities and support needs from available CRM context" in content
    assert "Follow up on Customer A Renewal" not in content
    assert_no_transport_secrets(result)


def test_generate_presales_weekly_table_outputs_markdown_table():
    from crm_mcp_server.report_drafts import generate_presales_weekly_table

    presales_context = context()
    presales_context["context_type"] = "presales_weekly"

    result = generate_presales_weekly_table(presales_context)

    content = result["content"]

    assert result["draft_type"] == "presales_weekly_table"
    assert "| Sales | Source | Project/Lead/Scenario |" in content
    assert "Customer A Renewal" in content
    assert "Scenario Lead" in content
    assert_no_transport_secrets(result)


def test_drafts_redact_broad_transport_markers_from_unsanitized_context():
    from crm_mcp_server.report_drafts import (
        generate_presales_weekly_table,
        generate_sales_daily_draft,
        generate_sales_weekly_draft,
    )

    unsafe_context = context()
    unsafe_context["scope"] = {"scope_id": "cookie=session-1", "owner_ids": [], "group_ids": []}
    unsafe_context["records"] = {
        "projects": [
            {"id": "project-1", "title": "Customer A Renewal", "summary": "auth: secret"},
            {"id": "project-2", "title": "Token Secret Account", "summary": "normal summary"},
        ],
        "activities": [{"id": "activity-1", "title": "Dinner Visit", "summary": "Cookie: session"}],
        "leads": [{"id": "lead-1", "title": "Scenario Lead", "summary": "crm token secret"}],
        "lead_pool": [{"id": "pool-1", "title": "Pool Lead", "summary": "normal summary"}],
        "scenarios": [{"id": "scenario-1", "title": "Industry Scenario", "summary": "RAW graphql trace"}],
    }

    for result in (
        generate_sales_daily_draft(unsafe_context),
        generate_sales_weekly_draft(unsafe_context),
        generate_presales_weekly_table(unsafe_context),
    ):
        assert "Customer A Renewal" in result["content"]
        assert_no_transport_secrets(result)


def assert_no_transport_secrets(result: dict[str, object]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for marker in (
        "raw GraphQL",
        "RAW graphql",
        "Authorization",
        "Bearer",
        "CRM_GRAPHQL_TOKEN",
        "cookie",
        "Cookie",
        "token secret",
        "Token Secret",
        "auth: secret",
    ):
        assert marker not in serialized
