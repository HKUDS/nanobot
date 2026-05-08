"""Synthetic read-only CRM adapter for tests and development verification."""

from __future__ import annotations

from nanobot.crm.models import OpportunityRecord, ReportRequest
from nanobot.crm.synthetic_data import CRMFixtureScenario


class MockCRMAdapter:
    """Read normalized synthetic CRM records from a fixture scenario."""

    def __init__(self, scenario: CRMFixtureScenario) -> None:
        self._scenario = scenario

    def read_opportunities(self, request: ReportRequest) -> tuple[OpportunityRecord, ...]:
        owner_ids = set(request.scope.owner_ids)
        return tuple(
            opportunity
            for opportunity in self._scenario.opportunities
            if request.window.start <= opportunity.updated_at.date() <= request.window.end
            and (not owner_ids or opportunity.owner_id in owner_ids)
        )
