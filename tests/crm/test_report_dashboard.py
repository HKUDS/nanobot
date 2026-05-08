from __future__ import annotations

from datetime import date

from nanobot.crm.models import ReportRequest, ReportScope, ReportType, ReportWindow
from nanobot.crm.reports import generate_dashboard_summary
from tests.crm.fixtures import dashboard_scenario


class SpyAdapter:
    def __init__(self, opportunities: tuple = ()) -> None:
        self.opportunities = opportunities

    def read_opportunities(self, request: ReportRequest) -> tuple:
        return self.opportunities


def _request() -> ReportRequest:
    return ReportRequest(
        report_type=ReportType.DASHBOARD,
        window=ReportWindow(start=date(2026, 1, 10), end=date(2026, 1, 16)),
        scope=ReportScope(scope_id="synthetic-team"),
    )


def test_dashboard_summary_has_fixed_sections() -> None:
    report = generate_dashboard_summary(_request(), SpyAdapter(dashboard_scenario().opportunities))

    assert report.report_type is ReportType.DASHBOARD
    assert list(report.sections) == [
        "included_sales_scope",
        "pipeline_status",
        "opportunity_stage_status",
        "risk_or_stagnation",
        "notable_movements",
        "evidence_traces",
    ]
    assert "owner_count.owner-alpha" in report.sections["included_sales_scope"]
    assert "pipeline_total_amount" in report.sections["pipeline_status"]
    assert "trace-owner-count-v1" in report.sections["evidence_traces"]
    assert report.evidence_traces


def test_dashboard_summary_does_not_expose_complex_bi_controls() -> None:
    report = generate_dashboard_summary(_request(), SpyAdapter(dashboard_scenario().opportunities))
    rendered = "\n".join(report.sections.values()).lower()

    forbidden = ["ad hoc", "interactive", "drill-down", "forecast", "custom query"]
    assert all(word not in rendered for word in forbidden)
