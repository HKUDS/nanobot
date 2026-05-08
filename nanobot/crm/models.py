"""Normalized CRM domain models for opportunity intelligence reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class ReportType(str, Enum):
    """First-version CRM report types."""

    DAILY = "daily"
    WEEKLY = "weekly"
    DASHBOARD = "dashboard"


@dataclass(frozen=True)
class ReportWindow:
    """Inclusive business date range for report generation."""

    start: date
    end: date


@dataclass(frozen=True)
class ReportScope:
    """Allowed report scope for deterministic CRM analysis."""

    scope_id: str
    owner_ids: tuple[str, ...] = ()
    team_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportRequest:
    """Input request shared by CLI, tools, DingTalk, and report generation."""

    report_type: ReportType
    window: ReportWindow
    scope: ReportScope


@dataclass(frozen=True)
class CRMSourceRef:
    """Stable CRM source reference used by evidence traces."""

    entity_type: str
    source_id: str
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpportunityRecord:
    """Normalized v1 opportunity record from a read-only CRM adapter."""

    opportunity_id: str
    title: str
    owner_id: str
    stage: str
    status: str
    amount: Decimal | None
    created_at: datetime
    updated_at: datetime
    expected_close_date: date | None
    source_ref: CRMSourceRef
    owner_name: str | None = None
    customer_id: str | None = None
    customer_name: str | None = None


@dataclass(frozen=True)
class ActivityRecord:
    """Normalized v1 activity record from GraphQL `Activity`."""

    activity_id: str | None
    type: str
    domain: str
    creator_id: str | None
    creator_name: str | None
    desc: str
    description: str | None
    link: str | None
    extra_desc: str | None
    created_at: datetime
    updated_at: datetime
    source_ref: CRMSourceRef


@dataclass(frozen=True)
class ReportRecord:
    """Normalized v1 report record from GraphQL `Report`."""

    report_id: str
    report_type: str
    target: datetime
    creator_id: str | None
    creator_name: str | None
    content: str
    created_at: datetime
    updated_at: datetime | None
    source_ref: CRMSourceRef


@dataclass(frozen=True)
class CustomerRecord:
    """Normalized v1 customer record from GraphQL `Company`."""

    customer_id: str
    name: str
    common_name: str | None
    claim_by_id: str | None
    claim_by_name: str | None
    industry_name: str | None
    region_name: str | None
    rank: str | None
    valid: bool
    created_at: datetime
    updated_at: datetime
    source_ref: CRMSourceRef


@dataclass(frozen=True)
class BusinessChanceRecord:
    """Normalized v1 partner business chance record."""

    chance_id: str
    company_id: str | None
    company_name: str
    project_name: str
    due_at: datetime
    claim_by_id: str | None
    claim_by_name: str | None
    info: str
    status: str
    apply_status: str
    source: str
    created_at: datetime
    updated_at: datetime
    source_ref: CRMSourceRef


@dataclass(frozen=True)
class SalesRepRecord:
    """Normalized v1 sales representative record from GraphQL `User`."""

    user_id: str
    username: str
    name: str
    roles: tuple[str, ...]
    enabled: bool
    updated_at: datetime | None
    source_ref: CRMSourceRef


@dataclass(frozen=True)
class MetricValue:
    """Typed deterministic metric value."""

    kind: str
    value: int | Decimal | str
    unit: str | None = None


@dataclass(frozen=True)
class MetricRecord:
    """Deterministic metric output with source references."""

    name: str
    value: MetricValue
    window: ReportWindow
    scope: ReportScope
    calculation_id: str
    source_refs: tuple[CRMSourceRef, ...] = ()


@dataclass(frozen=True)
class UnavailableMetricRecord:
    """Metric that cannot be computed because required inputs are absent."""

    name: str
    missing_inputs: tuple[str, ...]
    window: ReportWindow
    scope: ReportScope


@dataclass(frozen=True)
class EvidenceTrace:
    """Report-local evidence trace for a key business conclusion."""

    trace_id: str
    metric_name: str
    metric_value: MetricValue | None
    window: ReportWindow
    scope: ReportScope
    source_refs: tuple[CRMSourceRef, ...] = ()
    calculation_id: str | None = None


@dataclass(frozen=True)
class ReportOutput:
    """Structured CRM report output."""

    report_type: ReportType
    title: str
    sections: dict[str, str]
    metrics: tuple[MetricRecord, ...] = ()
    unavailable_metrics: tuple[UnavailableMetricRecord, ...] = ()
    evidence_traces: tuple[EvidenceTrace, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
