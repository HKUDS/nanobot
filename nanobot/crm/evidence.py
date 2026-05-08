"""Evidence trace construction for CRM reports."""

from __future__ import annotations

from nanobot.crm.models import EvidenceTrace, MetricRecord


def build_evidence_traces(metrics: tuple[MetricRecord, ...]) -> tuple[EvidenceTrace, ...]:
    """Create deterministic report-local trace records for metric-backed conclusions."""

    return tuple(
        EvidenceTrace(
            trace_id=f"trace-{metric.calculation_id}-{index:03d}",
            metric_name=metric.name,
            metric_value=metric.value,
            window=metric.window,
            scope=metric.scope,
            source_refs=metric.source_refs,
            calculation_id=metric.calculation_id,
        )
        for index, metric in enumerate(metrics, start=1)
    )
