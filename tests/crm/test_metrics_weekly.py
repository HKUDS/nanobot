from __future__ import annotations

from datetime import date

from nanobot.crm.metrics import compute_pipeline_metrics
from nanobot.crm.models import ReportScope, ReportWindow
from tests.crm.fixtures import weekly_scenario


def test_weekly_metrics_include_status_summaries() -> None:
    metrics, unavailable = compute_pipeline_metrics(
        weekly_scenario().opportunities,
        window=ReportWindow(start=date(2026, 1, 10), end=date(2026, 1, 16)),
        scope=ReportScope(scope_id="synthetic-team"),
    )
    by_name = {metric.name: metric.value.value for metric in metrics}

    assert unavailable == ()
    assert by_name["opportunity_count"] == 3
    assert by_name["status_count.open"] == 2
    assert by_name["status_count.won"] == 1
