"""Synthetic CRM data for mock-mode development and Docker smoke checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from nanobot.crm.models import CRMSourceRef, OpportunityRecord

SYNTHETIC_FIXTURE_LABEL = "synthetic-crm-fixtures"


@dataclass(frozen=True)
class CRMFixtureScenario:
    name: str
    synthetic_label: str
    opportunities: tuple[OpportunityRecord, ...]


def _opportunity(
    opportunity_id: str,
    title: str,
    owner_id: str,
    stage: str,
    status: str,
    amount: Decimal | None,
    updated_day: int,
) -> OpportunityRecord:
    fields = ("amount", "stage", "owner_id", "status", "updated_at")
    return OpportunityRecord(
        opportunity_id=opportunity_id,
        title=title,
        owner_id=owner_id,
        stage=stage,
        status=status,
        amount=amount,
        created_at=datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, updated_day, 10, 0, tzinfo=timezone.utc),
        expected_close_date=date(2026, 2, 1),
        source_ref=CRMSourceRef(
            entity_type="opportunity",
            source_id=opportunity_id,
            fields=fields,
        ),
    )


def daily_scenario() -> CRMFixtureScenario:
    return CRMFixtureScenario(
        name="daily",
        synthetic_label=SYNTHETIC_FIXTURE_LABEL,
        opportunities=(
            _opportunity(
                "synthetic-opportunity-001",
                "Synthetic Alpha Expansion",
                "owner-alpha",
                "proposal",
                "open",
                Decimal("12000.00"),
                15,
            ),
            _opportunity(
                "synthetic-opportunity-002",
                "Synthetic Beta Renewal",
                "owner-alpha",
                "negotiation",
                "open",
                Decimal("8000.00"),
                15,
            ),
        ),
    )


def weekly_scenario() -> CRMFixtureScenario:
    return CRMFixtureScenario(
        name="weekly",
        synthetic_label=SYNTHETIC_FIXTURE_LABEL,
        opportunities=(
            *daily_scenario().opportunities,
            _opportunity(
                "synthetic-opportunity-003",
                "Synthetic Gamma Pilot",
                "owner-beta",
                "won",
                "won",
                Decimal("5000.00"),
                16,
            ),
        ),
    )


def dashboard_scenario() -> CRMFixtureScenario:
    return CRMFixtureScenario(
        name="dashboard",
        synthetic_label=SYNTHETIC_FIXTURE_LABEL,
        opportunities=weekly_scenario().opportunities,
    )


def empty_scenario() -> CRMFixtureScenario:
    return CRMFixtureScenario(
        name="empty-data",
        synthetic_label=SYNTHETIC_FIXTURE_LABEL,
        opportunities=(),
    )


def missing_input_scenario() -> CRMFixtureScenario:
    return CRMFixtureScenario(
        name="missing-input",
        synthetic_label=SYNTHETIC_FIXTURE_LABEL,
        opportunities=(
            _opportunity(
                "synthetic-opportunity-004",
                "Synthetic Missing Amount",
                "owner-alpha",
                "proposal",
                "open",
                None,
                15,
            ),
        ),
    )


def multi_sales_user_scenario() -> CRMFixtureScenario:
    return CRMFixtureScenario(
        name="multi-sales-user",
        synthetic_label=SYNTHETIC_FIXTURE_LABEL,
        opportunities=dashboard_scenario().opportunities,
    )


ALL_SCENARIOS = (
    daily_scenario(),
    weekly_scenario(),
    dashboard_scenario(),
    empty_scenario(),
    missing_input_scenario(),
    multi_sales_user_scenario(),
)
