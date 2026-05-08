from __future__ import annotations

from datetime import date

import pytest

from nanobot.crm.models import ReportRequest, ReportScope, ReportType, ReportWindow
from nanobot.crm.reports import ReportValidationError, generate_weekly_report
from tests.crm.fixtures import weekly_scenario


class SpyAdapter:
    def __init__(self, opportunities: tuple = ()) -> None:
        self.opportunities = opportunities
        self.read_count = 0

    def read_opportunities(self, request: ReportRequest) -> tuple:
        self.read_count += 1
        return self.opportunities


def _request(window: ReportWindow | None = None) -> ReportRequest:
    return ReportRequest(
        report_type=ReportType.WEEKLY,
        window=window or ReportWindow(start=date(2026, 1, 10), end=date(2026, 1, 16)),
        scope=ReportScope(scope_id="synthetic-team"),
    )


def test_weekly_report_has_fixed_sections() -> None:
    report = generate_weekly_report(_request(), SpyAdapter(weekly_scenario().opportunities))

    assert report.report_type is ReportType.WEEKLY
    assert list(report.sections) == [
        "reporting_window",
        "scope",
        "pipeline_movement",
        "stage_distribution",
        "stalled_or_high_risk",
        "won_lost",
        "evidence_traces",
    ]
    assert "stage_count.proposal" in report.sections["stage_distribution"]
    assert "status_count.won" in report.sections["won_lost"]
    assert "trace-status-count-v1" in report.sections["evidence_traces"]
    assert report.evidence_traces


def test_weekly_report_does_not_claim_trend_without_metric() -> None:
    report = generate_weekly_report(_request(), SpyAdapter(weekly_scenario().opportunities))
    rendered = "\n".join(report.sections.values()).lower()

    assert "week-over-week" not in rendered
    assert "trend" not in rendered


def test_weekly_report_requires_window_before_adapter_read() -> None:
    adapter = SpyAdapter(())
    request = ReportRequest(
        report_type=ReportType.WEEKLY,
        window=None,  # type: ignore[arg-type]
        scope=ReportScope(scope_id="synthetic-team"),
    )

    with pytest.raises(ReportValidationError):
        generate_weekly_report(request, adapter)

    assert adapter.read_count == 0
