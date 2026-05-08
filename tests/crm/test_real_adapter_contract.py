from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from nanobot.crm.adapters import CRMAdapterError, CRMAdapterErrorCode
from nanobot.crm.graphql_client import CRMGraphQLClient
from nanobot.crm.models import (
    ActivityRecord,
    BusinessChanceRecord,
    CustomerRecord,
    OpportunityRecord,
    ReportRecord,
    ReportRequest,
    ReportScope,
    ReportType,
    ReportWindow,
)
from nanobot.crm.real_adapter import RealCRMAdapter

SYNTHETIC_ENDPOINT = "https://synthetic.invalid/graphql"
SYNTHETIC_CREDENTIAL = "synthetic-credential-value"


class RecordingTransport:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        *,
        endpoint: str,
        token: str,
        operation_name: str,
        query: str,
        variables: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append(
            {
                "endpoint": endpoint,
                "token": token,
                "operation_name": operation_name,
                "query": query,
                "variables": variables,
            }
        )
        return self.responses[operation_name]


def _request() -> ReportRequest:
    return ReportRequest(
        report_type=ReportType.DAILY,
        window=ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15)),
        scope=ReportScope(scope_id="synthetic-team", owner_ids=("owner-a",), team_ids=("team-a",)),
    )


def _adapter(responses: dict[str, dict[str, object]], page_limit: int = 10) -> tuple[RealCRMAdapter, RecordingTransport]:
    transport = RecordingTransport(responses)
    client = CRMGraphQLClient(
        endpoint=SYNTHETIC_ENDPOINT,
        token=SYNTHETIC_CREDENTIAL,
        transport=transport,
    )
    return RealCRMAdapter(client, page_limit=page_limit), transport


def test_read_opportunities_maps_list_project_to_normalized_records() -> None:
    adapter, transport = _adapter(
        {
            "listProject": {
                "data": {
                    "listProject": {
                        "total": 1,
                        "skip": 0,
                        "limit": 10,
                        "data": [
                            {
                                "id": "synthetic-project-001",
                                "name": "Synthetic Project Alpha",
                                "updated_at": "2026-01-15T10:00:00+00:00",
                                "created_at": "2026-01-10T09:00:00+00:00",
                                "stage": "proposal",
                                "deal_date": None,
                                "estimated_deal_date": "2026-02-01T00:00:00+00:00",
                                "sign_date": None,
                                "estimated_sign_date": None,
                                "win_rate": "60",
                                "claimBy": {"user": {"id": "owner-a", "name": "Synthetic Owner", "username": "synthetic.owner"}},
                                "company": {"id": "synthetic-company-001", "name": "Synthetic Company"},
                                "amount": {"value": "12000.00", "currency": "CNY"},
                                "actual_amount": {"value": "10000.00", "currency": "CNY"},
                            }
                        ],
                    }
                }
            }
        }
    )

    records = adapter.read_opportunities(_request())

    assert records == (
        OpportunityRecord(
            opportunity_id="synthetic-project-001",
            title="Synthetic Project Alpha",
            owner_id="owner-a",
            owner_name="Synthetic Owner",
            customer_id="synthetic-company-001",
            customer_name="Synthetic Company",
            stage="proposal",
            status="proposal",
            amount=Decimal("12000.00"),
            created_at=datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            expected_close_date=date(2026, 2, 1),
            source_ref=records[0].source_ref,
        ),
    )
    assert records[0].source_ref.entity_type == "Project"
    assert records[0].source_ref.source_id == "synthetic-project-001"
    assert transport.calls[0]["operation_name"] == "listProject"
    assert transport.calls[0]["variables"]["pagination"] == {"skip": 0, "limit": 10}
    assert transport.calls[0]["variables"]["search"]["sales"] == ["owner-a"]


def test_read_activities_maps_list_activity_to_normalized_records() -> None:
    adapter, _ = _adapter(
        {
            "listActivity": {
                "data": {
                    "listActivity": {
                        "total": 1,
                        "skip": 0,
                        "limit": 10,
                        "data": [
                            {
                                "type": "visit",
                                "domain": "project",
                                "desc": "Synthetic activity summary",
                                "description": "Synthetic activity description",
                                "link": "synthetic-link",
                                "extraDesc": "Synthetic extra context",
                                "created_at": "2026-01-15T09:30:00+00:00",
                                "updated_at": "2026-01-15T10:00:00+00:00",
                                "creator": {"id": "owner-a", "name": "Synthetic Owner", "username": "synthetic.owner"},
                            }
                        ],
                    }
                }
            }
        }
    )

    records = adapter.read_activities(_request())

    assert isinstance(records[0], ActivityRecord)
    assert records[0].activity_id is None
    assert records[0].type == "visit"
    assert records[0].creator_id == "owner-a"
    assert records[0].source_ref.entity_type == "Activity"


def test_read_reports_maps_list_report_to_normalized_records() -> None:
    adapter, _ = _adapter(
        {
            "listReport": {
                "data": {
                    "listReport": {
                        "total": 1,
                        "skip": 0,
                        "limit": 10,
                        "data": [
                            {
                                "id": "synthetic-report-001",
                                "type": "daily",
                                "created_at": "2026-01-15T18:00:00+00:00",
                                "updated_at": None,
                                "target": "2026-01-15T00:00:00+00:00",
                                "content": "Synthetic report content",
                                "creator": {"id": "owner-a", "name": "Synthetic Owner", "username": "synthetic.owner"},
                            }
                        ],
                    }
                }
            }
        }
    )

    records = adapter.read_reports(_request())

    assert records == (
        ReportRecord(
            report_id="synthetic-report-001",
            report_type="daily",
            target=datetime(2026, 1, 15, tzinfo=timezone.utc),
            creator_id="owner-a",
            creator_name="Synthetic Owner",
            content="Synthetic report content",
            created_at=datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc),
            updated_at=None,
            source_ref=records[0].source_ref,
        ),
    )


def test_read_customers_maps_list_company_to_normalized_records() -> None:
    adapter, _ = _adapter(
        {
            "listCompany": {
                "data": {
                    "listCompany": {
                        "total": 1,
                        "skip": 0,
                        "limit": 10,
                        "data": [
                            {
                                "id": "synthetic-company-001",
                                "name": "Synthetic Company",
                                "common_name": "Synthetic Co",
                                "valid": True,
                                "created_at": "2026-01-01T00:00:00+00:00",
                                "updated_at": "2026-01-15T00:00:00+00:00",
                                "claim_by": {"id": "owner-a", "name": "Synthetic Owner", "username": "synthetic.owner"},
                                "industry": {"id": "synthetic-industry", "name": "Synthetic Industry"},
                                "region": {"id": "synthetic-region", "name": "Synthetic Region"},
                                "rank": "A",
                            }
                        ],
                    }
                }
            }
        }
    )

    records = adapter.read_customers(_request())

    assert records == (
        CustomerRecord(
            customer_id="synthetic-company-001",
            name="Synthetic Company",
            common_name="Synthetic Co",
            claim_by_id="owner-a",
            claim_by_name="Synthetic Owner",
            industry_name="Synthetic Industry",
            region_name="Synthetic Region",
            rank="A",
            valid=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            source_ref=records[0].source_ref,
        ),
    )


def test_read_business_chances_maps_list_business_chance_to_normalized_records() -> None:
    adapter, _ = _adapter(
        {
            "list_business_chance": {
                "data": {
                    "list_business_chance": {
                        "total": 1,
                        "skip": 0,
                        "limit": 10,
                        "data": [
                            {
                                "id": "synthetic-chance-001",
                                "company_name": "Synthetic Company",
                                "project_name": "Synthetic Partner Chance",
                                "due_at": "2026-02-01T00:00:00+00:00",
                                "info": "Synthetic chance info",
                                "status": "open",
                                "apply_status": "approved",
                                "source": "partner",
                                "commit_at": "2026-01-12T00:00:00+00:00",
                                "created_at": "2026-01-10T00:00:00+00:00",
                                "updated_at": "2026-01-15T00:00:00+00:00",
                                "claim_by": {"id": "owner-a", "name": "Synthetic Owner", "username": "synthetic.owner"},
                                "company": {"id": "synthetic-company-001", "name": "Synthetic Company"},
                            }
                        ],
                    }
                }
            }
        }
    )

    records = adapter.read_business_chances(_request())

    assert records == (
        BusinessChanceRecord(
            chance_id="synthetic-chance-001",
            company_id="synthetic-company-001",
            company_name="Synthetic Company",
            project_name="Synthetic Partner Chance",
            due_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            claim_by_id="owner-a",
            claim_by_name="Synthetic Owner",
            info="Synthetic chance info",
            status="open",
            apply_status="approved",
            source="partner",
            created_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            source_ref=records[0].source_ref,
        ),
    )


def test_connection_pagination_continues_until_total_is_read() -> None:
    transport = RecordingTransport(
        {
            "listReport": {
                "data": {
                    "listReport": {
                        "total": 1,
                        "skip": 0,
                        "limit": 1,
                        "data": [
                            {
                                "id": "synthetic-report-001",
                                "type": "daily",
                                "created_at": "2026-01-15T18:00:00+00:00",
                                "updated_at": None,
                                "target": "2026-01-15T00:00:00+00:00",
                                "content": "Synthetic report content",
                                "creator": None,
                            }
                        ],
                    }
                }
            }
        }
    )
    client = CRMGraphQLClient(SYNTHETIC_ENDPOINT, SYNTHETIC_CREDENTIAL, transport)
    adapter = RealCRMAdapter(client, page_limit=1)

    records = adapter.read_reports(_request())

    assert len(records) == 1
    assert transport.calls[0]["variables"]["pagination"] == {"skip": 0, "limit": 1}


def test_missing_required_field_raises_sanitized_missing_data_error() -> None:
    adapter, _ = _adapter(
        {
            "listProject": {
                "data": {
                    "listProject": {
                        "total": 1,
                        "skip": 0,
                        "limit": 10,
                        "data": [
                            {
                                "id": "synthetic-project-raw-payload-should-not-leak",
                                "updated_at": "2026-01-15T10:00:00+00:00",
                                "created_at": "2026-01-10T09:00:00+00:00",
                            }
                        ],
                    }
                }
            }
        }
    )

    with pytest.raises(CRMAdapterError) as exc_info:
        adapter.read_opportunities(_request())

    message = str(exc_info.value)
    assert exc_info.value.code is CRMAdapterErrorCode.MISSING_DATA
    assert "missing required CRM field" in message
    assert "raw-payload-should-not-leak" not in message


def test_real_adapter_has_no_writeback_methods() -> None:
    forbidden_fragments = (
        "create",
        "update",
        "delete",
        "assign",
        "contact",
        "message",
        "task",
        "write",
        "createReport",
    )
    public_names = {name for name in dir(RealCRMAdapter) if not name.startswith("_")}

    assert not any(fragment.lower() in name.lower() for fragment in forbidden_fragments for name in public_names)
