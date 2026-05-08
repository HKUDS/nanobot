from __future__ import annotations

from datetime import date

from nanobot.crm.evidence import build_evidence_traces
from nanobot.crm.metrics import compute_pipeline_metrics
from nanobot.crm.models import ReportScope, ReportWindow
from tests.crm.fixtures import daily_scenario


def test_evidence_trace_builder_creates_trace_for_each_metric() -> None:
    window = ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15))
    scope = ReportScope(scope_id="synthetic-team")
    metrics, _ = compute_pipeline_metrics(daily_scenario().opportunities, window=window, scope=scope)

    traces = build_evidence_traces(metrics)

    assert len(traces) == len(metrics)
    assert traces[0].trace_id == "trace-opportunity-count-v1-001"
    assert traces[0].metric_name == metrics[0].name
    assert traces[0].window == window
    assert traces[0].scope == scope


def test_evidence_traces_do_not_include_sensitive_payloads() -> None:
    window = ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15))
    scope = ReportScope(scope_id="synthetic-team")
    metrics, _ = compute_pipeline_metrics(daily_scenario().opportunities, window=window, scope=scope)

    rendered = repr(build_evidence_traces(metrics)).lower()

    forbidden = ["token", "secret", "password", "raw_payload", "真实"]
    assert all(marker not in rendered for marker in forbidden)
