from __future__ import annotations

from datetime import date

from nanobot.crm.metrics import compute_pipeline_metrics
from nanobot.crm.models import ReportScope, ReportWindow
from tests.crm.fixtures import dashboard_scenario


def test_dashboard_metrics_include_owner_aggregation() -> None:
    metrics, unavailable = compute_pipeline_metrics(
        dashboard_scenario().opportunities,
        window=ReportWindow(start=date(2026, 1, 10), end=date(2026, 1, 16)),
        scope=ReportScope(scope_id="synthetic-team"),
    )
    by_name = {metric.name: metric.value.value for metric in metrics}

    assert unavailable == ()
    assert by_name["owner_count.owner-alpha"] == 2
    assert by_name["owner_count.owner-beta"] == 1
