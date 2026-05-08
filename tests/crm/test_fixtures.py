from __future__ import annotations

from decimal import Decimal

from tests.crm.fixtures import (
    ALL_SCENARIOS,
    SYNTHETIC_FIXTURE_LABEL,
    daily_scenario,
    dashboard_scenario,
    empty_scenario,
    missing_input_scenario,
    weekly_scenario,
)


def test_fixtures_are_explicitly_labeled_synthetic() -> None:
    assert SYNTHETIC_FIXTURE_LABEL == "synthetic-crm-fixtures"
    assert all(scenario.synthetic_label == SYNTHETIC_FIXTURE_LABEL for scenario in ALL_SCENARIOS)


def test_fixture_scenarios_cover_required_report_modes_and_edges() -> None:
    scenario_names = {scenario.name for scenario in ALL_SCENARIOS}

    assert {
        "daily",
        "weekly",
        "dashboard",
        "empty-data",
        "missing-input",
        "multi-sales-user",
    } <= scenario_names
    assert daily_scenario().opportunities
    assert weekly_scenario().opportunities
    assert dashboard_scenario().opportunities
    assert empty_scenario().opportunities == ()
    assert missing_input_scenario().opportunities[0].amount is None


def test_dashboard_fixture_contains_multiple_sales_users() -> None:
    owner_ids = {opportunity.owner_id for opportunity in dashboard_scenario().opportunities}

    assert owner_ids == {"owner-alpha", "owner-beta"}


def test_fixture_uses_deterministic_fake_amounts_and_source_ids() -> None:
    amounts = [opportunity.amount for opportunity in daily_scenario().opportunities]
    source_ids = [opportunity.source_ref.source_id for opportunity in daily_scenario().opportunities]

    assert amounts == [Decimal("12000.00"), Decimal("8000.00")]
    assert source_ids == ["synthetic-opportunity-001", "synthetic-opportunity-002"]


def test_fixture_strings_do_not_contain_sensitive_or_real_data_markers() -> None:
    fixture_text = repr(ALL_SCENARIOS).lower()

    forbidden = [
        "token",
        "secret",
        "password",
        "真实",
        "客户真实",
        "customer.com",
        "example.com",
        "corp.com",
    ]

    assert all(marker not in fixture_text for marker in forbidden)
