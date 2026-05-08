from __future__ import annotations

from datetime import date

from nanobot.crm.mock_adapter import MockCRMAdapter
from nanobot.crm.models import ReportRequest, ReportScope, ReportType, ReportWindow
from tests.crm.fixtures import empty_scenario, missing_input_scenario, weekly_scenario


def _request(
    start: date = date(2026, 1, 15),
    end: date = date(2026, 1, 15),
    owner_ids: tuple[str, ...] = (),
) -> ReportRequest:
    return ReportRequest(
        report_type=ReportType.DAILY,
        window=ReportWindow(start=start, end=end),
        scope=ReportScope(scope_id="synthetic-team", owner_ids=owner_ids),
    )


def test_mock_adapter_reads_synthetic_opportunities_by_window() -> None:
    adapter = MockCRMAdapter(weekly_scenario())

    opportunities = adapter.read_opportunities(_request())

    assert [item.opportunity_id for item in opportunities] == [
        "synthetic-opportunity-001",
        "synthetic-opportunity-002",
    ]


def test_mock_adapter_filters_by_owner_scope() -> None:
    adapter = MockCRMAdapter(weekly_scenario())

    opportunities = adapter.read_opportunities(_request(owner_ids=("owner-beta",)))

    assert opportunities == ()


def test_mock_adapter_supports_empty_and_missing_input_scenarios() -> None:
    assert MockCRMAdapter(empty_scenario()).read_opportunities(_request()) == ()

    missing_records = MockCRMAdapter(missing_input_scenario()).read_opportunities(_request())
    assert len(missing_records) == 1
    assert missing_records[0].amount is None


def test_mock_adapter_is_deterministic() -> None:
    adapter = MockCRMAdapter(weekly_scenario())
    request = _request(start=date(2026, 1, 10), end=date(2026, 1, 16))

    assert adapter.read_opportunities(request) == adapter.read_opportunities(request)


def test_mock_adapter_has_no_write_like_methods() -> None:
    forbidden = ("create", "update", "delete", "assign", "message", "contact", "write")
    public_names = [name.lower() for name in dir(MockCRMAdapter) if not name.startswith("_")]

    assert not any(fragment in name for fragment in forbidden for name in public_names)
