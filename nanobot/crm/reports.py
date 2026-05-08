"""CRM report assembly."""

from __future__ import annotations

from typing import Protocol

from nanobot.crm.evidence import build_evidence_traces
from nanobot.crm.metrics import compute_pipeline_metrics
from nanobot.crm.models import EvidenceTrace, ReportOutput, ReportRequest, ReportType


class ReportValidationError(ValueError):
    """Report request failed validation before CRM access."""


class _OpportunityReader(Protocol):
    def read_opportunities(self, request: ReportRequest) -> tuple: ...


def generate_daily_report(request: ReportRequest, adapter: _OpportunityReader) -> ReportOutput:
    """Generate a deterministic daily report without LLM narrative."""

    if request.window is None:
        raise ReportValidationError("daily report requires an explicit reporting window")

    opportunities = adapter.read_opportunities(request)
    metrics, unavailable = compute_pipeline_metrics(
        opportunities,
        window=request.window,
        scope=request.scope,
    )
    traces = build_evidence_traces(metrics)

    if not opportunities:
        key_changes = "No matching data was found for the requested daily window."
    else:
        key_changes = "Key changes or risks require deterministic metrics or explicit CRM fields."

    sections = {
        "reporting_window": f"{request.window.start.isoformat()} to {request.window.end.isoformat()}",
        "scope": request.scope.scope_id,
        "deterministic_metrics": _render_metrics(metrics, unavailable),
        "key_changes_or_risks": key_changes,
        "evidence_traces": _render_traces(traces),
    }

    return ReportOutput(
        report_type=ReportType.DAILY,
        title="Sales Daily Report",
        sections=sections,
        metrics=metrics,
        unavailable_metrics=unavailable,
        evidence_traces=traces,
    )


def generate_weekly_report(request: ReportRequest, adapter: _OpportunityReader) -> ReportOutput:
    """Generate a deterministic weekly report without LLM narrative."""

    if request.window is None:
        raise ReportValidationError("weekly report requires an explicit reporting window")

    opportunities = adapter.read_opportunities(request)
    metrics, unavailable = compute_pipeline_metrics(
        opportunities,
        window=request.window,
        scope=request.scope,
    )
    traces = build_evidence_traces(metrics)

    sections = {
        "reporting_window": f"{request.window.start.isoformat()} to {request.window.end.isoformat()}",
        "scope": request.scope.scope_id,
        "pipeline_movement": _render_metrics(metrics, unavailable),
        "stage_distribution": _render_named_metrics(metrics, "stage_count."),
        "stalled_or_high_risk": "Unavailable until deterministic risk or stalled metrics exist.",
        "won_lost": _render_named_metrics(metrics, "status_count."),
        "evidence_traces": _render_traces(traces),
    }

    return ReportOutput(
        report_type=ReportType.WEEKLY,
        title="Sales Weekly Report",
        sections=sections,
        metrics=metrics,
        unavailable_metrics=unavailable,
        evidence_traces=traces,
    )


def generate_dashboard_summary(request: ReportRequest, adapter: _OpportunityReader) -> ReportOutput:
    """Generate a deterministic opportunity dashboard summary."""

    if request.window is None:
        raise ReportValidationError("dashboard summary requires an explicit reporting window")

    opportunities = adapter.read_opportunities(request)
    metrics, unavailable = compute_pipeline_metrics(
        opportunities,
        window=request.window,
        scope=request.scope,
    )
    traces = build_evidence_traces(metrics)

    sections = {
        "included_sales_scope": _render_named_metrics(metrics, "owner_count."),
        "pipeline_status": _render_metrics(metrics, unavailable),
        "opportunity_stage_status": "\n".join(
            part
            for part in (
                _render_named_metrics(metrics, "stage_count."),
                _render_named_metrics(metrics, "status_count."),
            )
            if part != "unavailable"
        ),
        "risk_or_stagnation": "Unavailable until deterministic risk or stagnation metrics exist.",
        "notable_movements": "Unavailable until deterministic movement metrics exist.",
        "evidence_traces": _render_traces(traces),
    }

    return ReportOutput(
        report_type=ReportType.DASHBOARD,
        title="Opportunity Dashboard Summary",
        sections=sections,
        metrics=metrics,
        unavailable_metrics=unavailable,
        evidence_traces=traces,
    )


def _render_metrics(metrics: tuple, unavailable: tuple) -> str:
    lines = [f"{metric.name}: {metric.value.value}" for metric in metrics]
    lines.extend(
        f"{metric.name}: unavailable, missing inputs: {', '.join(metric.missing_inputs)}"
        for metric in unavailable
    )
    return "\n".join(lines)


def _render_named_metrics(metrics: tuple, prefix: str) -> str:
    lines = [f"{metric.name}: {metric.value.value}" for metric in metrics if metric.name.startswith(prefix)]
    return "\n".join(lines) if lines else "unavailable"


def _render_traces(traces: tuple[EvidenceTrace, ...]) -> str:
    if not traces:
        return "no evidence traces"
    return "\n".join(
        f"{trace.trace_id}: {trace.metric_name} via {trace.calculation_id}" for trace in traces
    )
