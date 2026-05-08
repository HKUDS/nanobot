from __future__ import annotations

import inspect
from datetime import date

from nanobot.crm.adapters import CRMAdapter, CRMAdapterError, CRMAdapterErrorCode
from nanobot.crm.models import ReportRequest, ReportScope, ReportType, ReportWindow


def test_crm_adapter_exposes_only_read_methods() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(CRMAdapter)
        if not name.startswith("_") and callable(value)
    }

    assert public_methods == {
        "read_activities",
        "read_business_chances",
        "read_customers",
        "read_opportunities",
        "read_reports",
    }


def test_crm_adapter_does_not_expose_write_like_methods() -> None:
    forbidden_fragments = {
        "create",
        "update",
        "delete",
        "assign",
        "message",
        "contact",
        "write",
    }
    public_names = {name for name in dir(CRMAdapter) if not name.startswith("_")}

    assert not any(
        fragment in name.lower()
        for fragment in forbidden_fragments
        for name in public_names
    )


def test_adapter_error_categories_are_stable_and_sanitized() -> None:
    assert {code.value for code in CRMAdapterErrorCode} == {
        "crm_unavailable",
        "invalid_configuration",
        "invalid_scope",
        "missing_data",
    }

    error = CRMAdapterError(CRMAdapterErrorCode.CRM_UNAVAILABLE, "CRM read failed")

    assert error.code is CRMAdapterErrorCode.CRM_UNAVAILABLE
    assert str(error) == "CRM read failed"


def test_report_request_type_is_accepted_by_adapter_contract() -> None:
    signature = inspect.signature(CRMAdapter.read_opportunities)
    request = ReportRequest(
        report_type=ReportType.DAILY,
        window=ReportWindow(start=date(2026, 1, 15), end=date(2026, 1, 15)),
        scope=ReportScope(scope_id="synthetic-team"),
    )

    assert "request" in signature.parameters
    assert request.report_type is ReportType.DAILY
