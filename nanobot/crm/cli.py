"""CLI helpers for CRM opportunity intelligence reports."""

from __future__ import annotations

from datetime import date

from nanobot.crm.mock_adapter import MockCRMAdapter
from nanobot.crm.models import ReportOutput, ReportRequest, ReportScope, ReportType, ReportWindow
from nanobot.crm.reports import (
    generate_daily_report,
    generate_dashboard_summary,
    generate_weekly_report,
)
from nanobot.crm.synthetic_data import daily_scenario, dashboard_scenario, weekly_scenario


def generate_mock_report(
    report_type: ReportType,
    *,
    report_date: date | None,
    start: date | None,
    end: date | None,
    scope_id: str,
) -> ReportOutput:
    """Generate a report from synthetic mock data for CLI verification."""

    if report_type is ReportType.DAILY:
        if report_date is None:
            raise ValueError("daily report requires --date")
        window = ReportWindow(start=report_date, end=report_date)
        request = ReportRequest(report_type=report_type, window=window, scope=ReportScope(scope_id=scope_id))
        return generate_daily_report(request, MockCRMAdapter(daily_scenario()))

    if start is None or end is None:
        raise ValueError(f"{report_type.value} report requires --start and --end")

    window = ReportWindow(start=start, end=end)
    request = ReportRequest(report_type=report_type, window=window, scope=ReportScope(scope_id=scope_id))

    if report_type is ReportType.WEEKLY:
        return generate_weekly_report(request, MockCRMAdapter(weekly_scenario()))
    if report_type is ReportType.DASHBOARD:
        return generate_dashboard_summary(request, MockCRMAdapter(dashboard_scenario()))

    raise ValueError(f"unsupported report type: {report_type.value}")


def render_report_output(report: ReportOutput) -> str:
    """Render a structured report as plain text for terminal output."""

    lines = [report.title]
    for name, content in report.sections.items():
        lines.append(f"\n## {name}")
        lines.append(content)
    return "\n".join(lines)
