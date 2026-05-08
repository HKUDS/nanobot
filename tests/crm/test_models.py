from __future__ import annotations

import ast
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from nanobot.crm.models import (
    ActivityRecord,
    BusinessChanceRecord,
    CRMSourceRef,
    CustomerRecord,
    EvidenceTrace,
    MetricRecord,
    MetricValue,
    OpportunityRecord,
    ReportOutput,
    ReportRecord,
    ReportRequest,
    ReportScope,
    ReportType,
    ReportWindow,
    SalesRepRecord,
    UnavailableMetricRecord,
)


def test_report_request_models_support_v1_scope_and_window() -> None:
    request = ReportRequest(
        report_type=ReportType.DAILY,
        window=ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15)),
        scope=ReportScope(scope_id="synthetic-team", owner_ids=("owner-a",)),
    )

    assert request.report_type is ReportType.DAILY
    assert request.window.start == date(2026, 1, 15)
    assert request.scope.scope_id == "synthetic-team"
    assert request.scope.owner_ids == ("owner-a",)


def test_source_opportunity_model_carries_stable_reference_and_allowed_fields() -> None:
    source_ref = CRMSourceRef(
        entity_type="opportunity",
        source_id="synthetic-opportunity-001",
        fields=("amount", "stage", "owner_id"),
    )
    opportunity = OpportunityRecord(
        opportunity_id="synthetic-opportunity-001",
        title="Synthetic Opportunity Alpha",
        owner_id="owner-a",
        stage="proposal",
        status="open",
        amount=Decimal("12000.00"),
        created_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        expected_close_date=date(2026, 2, 1),
        source_ref=source_ref,
    )

    assert opportunity.source_ref == source_ref
    assert opportunity.amount == Decimal("12000.00")
    assert opportunity.source_ref.fields == ("amount", "stage", "owner_id")


def test_project_backed_opportunity_record_supports_v1_graphql_fields() -> None:
    payload = {
        "id": "synthetic-project-001",
        "name": "Synthetic Project Alpha",
        "stage": "proposal",
        "status": "open",
        "claimBy": {"user": {"id": "owner-a", "name": "Synthetic Owner"}},
        "company": {"id": "synthetic-company-001", "name": "Synthetic Company"},
        "amount": Decimal("12000.00"),
        "created_at": datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        "estimated_deal_date": date(2026, 2, 1),
    }
    source_ref = CRMSourceRef(
        entity_type="Project",
        source_id=payload["id"],
        fields=("id", "name", "stage", "amount", "claimBy.user.id", "company.id"),
    )

    opportunity = OpportunityRecord(
        opportunity_id=payload["id"],
        title=payload["name"],
        owner_id=payload["claimBy"]["user"]["id"],
        owner_name=payload["claimBy"]["user"]["name"],
        customer_id=payload["company"]["id"],
        customer_name=payload["company"]["name"],
        stage=payload["stage"],
        status=payload["status"],
        amount=payload["amount"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        expected_close_date=payload["estimated_deal_date"],
        source_ref=source_ref,
    )

    assert opportunity.source_ref.entity_type == "Project"
    assert opportunity.owner_name == "Synthetic Owner"
    assert opportunity.customer_id == "synthetic-company-001"
    assert opportunity.customer_name == "Synthetic Company"


def test_metric_unavailable_trace_and_report_models_are_instantiable() -> None:
    metric = MetricRecord(
        name="pipeline_total_amount",
        value=MetricValue(kind="amount", value=Decimal("12000.00"), unit="CNY"),
        window=ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15)),
        scope=ReportScope(scope_id="synthetic-team"),
        calculation_id="pipeline-total-v1",
        source_refs=(
            CRMSourceRef(
                entity_type="opportunity",
                source_id="synthetic-opportunity-001",
                fields=("amount",),
            ),
        ),
    )
    unavailable = UnavailableMetricRecord(
        name="stage_distribution",
        missing_inputs=("stage",),
        window=metric.window,
        scope=metric.scope,
    )
    trace = EvidenceTrace(
        trace_id="trace-001",
        metric_name=metric.name,
        metric_value=metric.value,
        window=metric.window,
        scope=metric.scope,
        source_refs=metric.source_refs,
        calculation_id=metric.calculation_id,
    )
    report = ReportOutput(
        report_type=ReportType.DAILY,
        title="Synthetic Daily Report",
        sections={"metrics": "Pipeline total amount: 12000.00"},
        metrics=(metric,),
        unavailable_metrics=(unavailable,),
        evidence_traces=(trace,),
    )

    assert report.metrics == (metric,)
    assert report.unavailable_metrics == (unavailable,)
    assert report.evidence_traces[0].trace_id == "trace-001"


def test_activity_record_can_be_constructed_from_synthetic_graphql_payload() -> None:
    payload = {
        "id": "synthetic-activity-001",
        "type": "visit",
        "domain": "project",
        "creator": {"id": "owner-a", "name": "Synthetic Owner"},
        "desc": "Synthetic activity summary",
        "description": "Synthetic activity description",
        "link": "synthetic-link",
        "extraDesc": "Synthetic extra context",
        "created_at": datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
    }

    activity = ActivityRecord(
        activity_id=payload["id"],
        type=payload["type"],
        domain=payload["domain"],
        creator_id=payload["creator"]["id"],
        creator_name=payload["creator"]["name"],
        desc=payload["desc"],
        description=payload["description"],
        link=payload["link"],
        extra_desc=payload["extraDesc"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        source_ref=CRMSourceRef(
            entity_type="Activity",
            source_id=payload["id"],
            fields=("type", "domain", "creator.id", "created_at", "updated_at"),
        ),
    )

    assert activity.activity_id == "synthetic-activity-001"
    assert activity.creator_id == "owner-a"
    assert activity.extra_desc == "Synthetic extra context"


def test_report_record_can_be_constructed_from_synthetic_graphql_payload() -> None:
    payload = {
        "id": "synthetic-report-001",
        "type": "daily",
        "target": datetime(2026, 1, 15, tzinfo=timezone.utc),
        "creator": {"id": "owner-a", "name": "Synthetic Owner"},
        "content": "Synthetic report content",
        "created_at": datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc),
        "updated_at": None,
    }

    report = ReportRecord(
        report_id=payload["id"],
        report_type=payload["type"],
        target=payload["target"],
        creator_id=payload["creator"]["id"],
        creator_name=payload["creator"]["name"],
        content=payload["content"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        source_ref=CRMSourceRef(
            entity_type="Report",
            source_id=payload["id"],
            fields=("type", "target", "creator.id", "content"),
        ),
    )

    assert report.report_type == "daily"
    assert report.creator_name == "Synthetic Owner"
    assert report.updated_at is None


def test_customer_record_can_be_constructed_from_synthetic_graphql_payload() -> None:
    payload = {
        "id": "synthetic-company-001",
        "name": "Synthetic Company",
        "common_name": "Synthetic Co",
        "claim_by": {"id": "owner-a", "name": "Synthetic Owner"},
        "industry": {"name": "Synthetic Industry"},
        "region": {"name": "Synthetic Region"},
        "rank": "A",
        "valid": True,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
    }

    customer = CustomerRecord(
        customer_id=payload["id"],
        name=payload["name"],
        common_name=payload["common_name"],
        claim_by_id=payload["claim_by"]["id"],
        claim_by_name=payload["claim_by"]["name"],
        industry_name=payload["industry"]["name"],
        region_name=payload["region"]["name"],
        rank=payload["rank"],
        valid=payload["valid"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        source_ref=CRMSourceRef(
            entity_type="Company",
            source_id=payload["id"],
            fields=("id", "name", "claim_by.id", "industry.name", "region.name"),
        ),
    )

    assert customer.customer_id == "synthetic-company-001"
    assert customer.claim_by_name == "Synthetic Owner"
    assert customer.valid is True


def test_business_chance_record_can_be_constructed_from_synthetic_graphql_payload() -> None:
    payload = {
        "id": "synthetic-chance-001",
        "company": {"id": "synthetic-company-001", "name": "Synthetic Company"},
        "company_name": "Synthetic Company",
        "project_name": "Synthetic Partner Chance",
        "due_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
        "claim_by": {"id": "owner-a", "name": "Synthetic Owner"},
        "info": "Synthetic chance info",
        "status": "open",
        "apply_status": "approved",
        "source": "partner",
        "created_at": datetime(2026, 1, 10, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
    }

    chance = BusinessChanceRecord(
        chance_id=payload["id"],
        company_id=payload["company"]["id"],
        company_name=payload["company_name"],
        project_name=payload["project_name"],
        due_at=payload["due_at"],
        claim_by_id=payload["claim_by"]["id"],
        claim_by_name=payload["claim_by"]["name"],
        info=payload["info"],
        status=payload["status"],
        apply_status=payload["apply_status"],
        source=payload["source"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        source_ref=CRMSourceRef(
            entity_type="BusinessChance",
            source_id=payload["id"],
            fields=("id", "project_name", "claim_by.id", "status", "apply_status"),
        ),
    )

    assert chance.chance_id == "synthetic-chance-001"
    assert chance.claim_by_id == "owner-a"
    assert chance.source == "partner"


def test_sales_rep_record_can_be_constructed_from_synthetic_graphql_payload() -> None:
    payload = {
        "id": "owner-a",
        "username": "synthetic.owner",
        "name": "Synthetic Owner",
        "role": ["sales"],
        "enabled": True,
        "updatedAt": datetime(2026, 1, 15, tzinfo=timezone.utc),
    }

    sales_rep = SalesRepRecord(
        user_id=payload["id"],
        username=payload["username"],
        name=payload["name"],
        roles=tuple(payload["role"]),
        enabled=payload["enabled"],
        updated_at=payload["updatedAt"],
        source_ref=CRMSourceRef(
            entity_type="User",
            source_id=payload["id"],
            fields=("id", "username", "name", "role", "enabled"),
        ),
    )

    assert sales_rep.user_id == "owner-a"
    assert sales_rep.roles == ("sales",)
    assert sales_rep.enabled is True


def test_source_references_do_not_contain_secret_markers() -> None:
    forbidden = ("to" + "ken", "sec" + "ret")
    refs = (
        CRMSourceRef(entity_type="Project", source_id="synthetic-project-001", fields=("id", "name")),
        CRMSourceRef(entity_type="Activity", source_id="synthetic-activity-001", fields=("type",)),
        CRMSourceRef(entity_type="Report", source_id="synthetic-report-001", fields=("content",)),
        CRMSourceRef(entity_type="Company", source_id="synthetic-company-001", fields=("name",)),
        CRMSourceRef(entity_type="BusinessChance", source_id="synthetic-chance-001", fields=("status",)),
        CRMSourceRef(entity_type="User", source_id="owner-a", fields=("name",)),
    )

    serialized_refs = " ".join(
        f"{ref.entity_type} {ref.source_id} {' '.join(ref.fields)}".lower() for ref in refs
    )

    assert all(marker not in serialized_refs for marker in forbidden)


@pytest.mark.parametrize(
    "forbidden_import",
    ["dingtalk", "nanobot.cli", "nanobot.providers", "httpx", "mcp"],
)
def test_models_module_does_not_import_runtime_integration_code(forbidden_import: str) -> None:
    source = Path("nanobot/crm/models.py").read_text()
    tree = ast.parse(source)

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert forbidden_import not in imports


def test_models_module_does_not_contain_transport_or_write_concerns() -> None:
    source = Path("nanobot/crm/models.py").read_text()
    forbidden_fragments = (
        "api.in.chaitin.net",
        "real_adapter",
        "Mutation",
        "mutation",
        "httpx",
    )

    assert all(fragment not in source for fragment in forbidden_fragments)
