from __future__ import annotations

from datetime import date
from decimal import Decimal

from nanobot.crm.metrics import compute_pipeline_metrics
from nanobot.crm.models import ReportScope, ReportWindow
from tests.crm.fixtures import daily_scenario


def test_daily_metrics_compute_count_and_total_amount() -> None:
    metrics, unavailable = compute_pipeline_metrics(
        daily_scenario().opportunities,
        window=ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15)),
        scope=ReportScope(scope_id="synthetic-team"),
    )
    by_name = {metric.name: metric for metric in metrics}

    assert unavailable == ()
    assert by_name["opportunity_count"].value.value == 2
    assert by_name["pipeline_total_amount"].value.value == Decimal("20000.00")
    assert by_name["pipeline_total_amount"].calculation_id == "pipeline-total-amount-v1"


def test_daily_metrics_include_stage_distribution() -> None:
    metrics, _ = compute_pipeline_metrics(
        daily_scenario().opportunities,
        window=ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15)),
        scope=ReportScope(scope_id="synthetic-team"),
    )
    stage_metrics = {metric.name: metric.value.value for metric in metrics}

    assert stage_metrics["stage_count.proposal"] == 1
    assert stage_metrics["stage_count.negotiation"] == 1
