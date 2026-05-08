"""Read-only CRM adapter boundary."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from nanobot.crm.models import (
    ActivityRecord,
    BusinessChanceRecord,
    CustomerRecord,
    OpportunityRecord,
    ReportRecord,
    ReportRequest,
)


class CRMAdapterErrorCode(str, Enum):
    """Stable sanitized adapter error categories."""

    CRM_UNAVAILABLE = "crm_unavailable"
    INVALID_CONFIGURATION = "invalid_configuration"
    INVALID_SCOPE = "invalid_scope"
    MISSING_DATA = "missing_data"


class CRMAdapterError(Exception):
    """Sanitized adapter error with a stable category."""

    def __init__(self, code: CRMAdapterErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class CRMAdapter(Protocol):
    """Read-only CRM adapter contract for v1 reports."""

    def read_opportunities(self, request: ReportRequest) -> tuple[OpportunityRecord, ...]:
        """Read normalized opportunity records for a report request."""

    def read_activities(self, request: ReportRequest) -> tuple[ActivityRecord, ...]:
        """Read normalized activity records for a report request."""

    def read_reports(self, request: ReportRequest) -> tuple[ReportRecord, ...]:
        """Read normalized report records for a report request."""

    def read_customers(self, request: ReportRequest) -> tuple[CustomerRecord, ...]:
        """Read normalized customer records for a report request."""

    def read_business_chances(self, request: ReportRequest) -> tuple[BusinessChanceRecord, ...]:
        """Read normalized business chance records for a report request."""
