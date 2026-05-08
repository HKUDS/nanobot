from __future__ import annotations

from typer.testing import CliRunner

from nanobot.cli.commands import app

runner = CliRunner()


def test_crm_cli_generates_daily_report_with_mock_adapter() -> None:
    result = runner.invoke(
        app,
        ["crm", "report", "daily", "--adapter", "mock", "--date", "2026-01-15", "--scope", "synthetic-team"],
    )

    assert result.exit_code == 0
    assert "Sales Daily Report" in result.output
    assert "pipeline_total_amount" in result.output
    assert "trace-pipeline-total-amount-v1" in result.output


def test_crm_cli_generates_weekly_report_with_mock_adapter() -> None:
    result = runner.invoke(
        app,
        [
            "crm",
            "report",
            "weekly",
            "--adapter",
            "mock",
            "--start",
            "2026-01-10",
            "--end",
            "2026-01-16",
            "--scope",
            "synthetic-team",
        ],
    )

    assert result.exit_code == 0
    assert "Sales Weekly Report" in result.output
    assert "status_count.won" in result.output


def test_crm_cli_generates_dashboard_summary_with_mock_adapter() -> None:
    result = runner.invoke(
        app,
        [
            "crm",
            "report",
            "dashboard",
            "--adapter",
            "mock",
            "--start",
            "2026-01-10",
            "--end",
            "2026-01-16",
            "--scope",
            "synthetic-team",
        ],
    )

    assert result.exit_code == 0
    assert "Opportunity Dashboard Summary" in result.output
    assert "owner_count.owner-alpha" in result.output


def test_crm_cli_returns_validation_error_without_required_date() -> None:
    result = runner.invoke(
        app,
        ["crm", "report", "daily", "--adapter", "mock", "--scope", "synthetic-team"],
    )

    assert result.exit_code != 0
    assert "date" in result.output.lower()
