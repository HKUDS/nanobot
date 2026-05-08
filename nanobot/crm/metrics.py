"""Deterministic CRM opportunity metrics."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from nanobot.crm.models import (
    MetricRecord,
    MetricValue,
    OpportunityRecord,
    ReportScope,
    ReportWindow,
    UnavailableMetricRecord,
)


def compute_pipeline_metrics(
    opportunities: tuple[OpportunityRecord, ...],
    *,
    window: ReportWindow,
    scope: ReportScope,
) -> tuple[tuple[MetricRecord, ...], tuple[UnavailableMetricRecord, ...]]:
    """Compute deterministic pipeline metrics for normalized opportunity records."""

    metrics: list[MetricRecord] = [
        MetricRecord(
            name="opportunity_count",
            value=MetricValue(kind="count", value=len(opportunities)),
            window=window,
            scope=scope,
            calculation_id="opportunity-count-v1",
            source_refs=tuple(opportunity.source_ref for opportunity in opportunities),
        )
    ]
    unavailable: list[UnavailableMetricRecord] = []

    amounts = [opportunity.amount for opportunity in opportunities]
    if any(amount is None for amount in amounts):
        unavailable.append(
            UnavailableMetricRecord(
                name="pipeline_total_amount",
                missing_inputs=("amount",),
                window=window,
                scope=scope,
            )
        )
    else:
        metrics.append(
            MetricRecord(
                name="pipeline_total_amount",
                value=MetricValue(
                    kind="amount",
                    value=sum((amount for amount in amounts if amount is not None), Decimal("0.00")),
                    unit="CNY",
                ),
                window=window,
                scope=scope,
                calculation_id="pipeline-total-amount-v1",
                source_refs=tuple(opportunity.source_ref for opportunity in opportunities),
            )
        )

    metrics.extend(
        _counter_metrics("stage_count", "stage-count-v1", Counter(o.stage for o in opportunities), window, scope)
    )
    metrics.extend(
        _counter_metrics(
            "status_count", "status-count-v1", Counter(o.status for o in opportunities), window, scope
        )
    )
    metrics.extend(
        _counter_metrics(
            "owner_count", "owner-count-v1", Counter(o.owner_id for o in opportunities), window, scope
        )
    )

    return tuple(metrics), tuple(unavailable)


def _counter_metrics(
    prefix: str,
    calculation_id: str,
    counts: Counter[str],
    window: ReportWindow,
    scope: ReportScope,
) -> tuple[MetricRecord, ...]:
    return tuple(
        MetricRecord(
            name=f"{prefix}.{name}",
            value=MetricValue(kind="count", value=count),
            window=window,
            scope=scope,
            calculation_id=calculation_id,
        )
        for name, count in sorted(counts.items())
    )
