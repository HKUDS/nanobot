from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

from nanobot.crm.metrics import compute_pipeline_metrics
from nanobot.crm.models import ReportScope, ReportWindow
from tests.crm.fixtures import missing_input_scenario


def test_missing_amount_produces_unavailable_total_amount_metric() -> None:
    metrics, unavailable = compute_pipeline_metrics(
        missing_input_scenario().opportunities,
        window=ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15)),
        scope=ReportScope(scope_id="synthetic-team"),
    )

    assert "pipeline_total_amount" not in {metric.name for metric in metrics}
    assert unavailable[0].name == "pipeline_total_amount"
    assert unavailable[0].missing_inputs == ("amount",)


def test_metrics_module_does_not_import_runtime_or_llm_integrations() -> None:
    source = Path("nanobot/crm/metrics.py").read_text()
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    forbidden = {"nanobot.cli", "nanobot.channels.dingtalk", "nanobot.providers", "openai", "anthropic"}
    assert imports.isdisjoint(forbidden)
