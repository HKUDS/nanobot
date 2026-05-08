from __future__ import annotations

from datetime import date

import pytest

from nanobot.crm.models import ReportRequest, ReportScope, ReportType, ReportWindow
from nanobot.crm.reports import ReportValidationError, generate_daily_report


class SpyAdapter:
    def __init__(self, opportunities: tuple = ()) -> None:
        self.opportunities = opportunities
        self.read_count = 0

    def read_opportunities(self, request: ReportRequest) -> tuple:
        self.read_count += 1
        return self.opportunities


def _request(window: ReportWindow | None = None) -> ReportRequest:
    return ReportRequest(
        report_type=ReportType.DAILY,
        window=window or ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15)),
        scope=ReportScope(scope_id="synthetic-team"),
    )


def test_daily_report_has_fixed_sections() -> None:
    from tests.crm.fixtures import daily_scenario

    report = generate_daily_report(_request(), SpyAdapter(daily_scenario().opportunities))

    assert report.report_type is ReportType.DAILY
    assert list(report.sections) == [
        "reporting_window",
        "scope",
        "deterministic_metrics",
        "key_changes_or_risks",
        "evidence_traces",
    ]
    assert "pipeline_total_amount" in report.sections["deterministic_metrics"]
    assert "trace-pipeline-total-amount-v1" in report.sections["evidence_traces"]
    assert report.evidence_traces


def test_daily_report_no_data_does_not_invent_activity() -> None:
    report = generate_daily_report(_request(), SpyAdapter(()))

    rendered = "\n".join(report.sections.values()).lower()

    assert "no matching data was found" in rendered
    assert "synthetic opportunity" not in rendered


def test_daily_report_requires_window_before_adapter_read() -> None:
    adapter = SpyAdapter(())
    request = ReportRequest(
        report_type=ReportType.DAILY,
        window=None,  # type: ignore[arg-type]
        scope=ReportScope(scope_id="synthetic-team"),
    )

    with pytest.raises(ReportValidationError):
        generate_daily_report(request, adapter)

    assert adapter.read_count == 0
