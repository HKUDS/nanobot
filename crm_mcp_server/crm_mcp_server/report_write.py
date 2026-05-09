"""Confirmation-gated CRM report write flow."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any, Mapping, Protocol

from crm_mcp_server.graphql import GraphQLContractError, build_create_report_mutation
from crm_mcp_server.redaction import sanitize_errors
from crm_mcp_server.report_context import sanitize_transport_detail

REPORT_TYPE_CONFIRMATION_TEXTS = {
    "daily": "确认提交这份日报",
    "weekly": "确认提交这份周报",
}
CONFIRMATION_TEXTS = set(REPORT_TYPE_CONFIRMATION_TEXTS.values())
_PACKAGE_SIGNATURE_SECRET = secrets.token_bytes(32)
REDACTED_STRUCTURED_DETAIL = "[redacted structured detail]"


class ReportWriteTransport(Protocol):
    auth_mode: str | None
    http_status_category: str | None
    status_code_category: str | None
    transport_error_category: str | None

    def execute(self, operation_name: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        ...


def prepare_create_report_confirmation(
    *,
    draft: Mapping[str, object],
    report_type: str,
    target: str,
    to: list[str],
) -> dict[str, object]:
    content = _safe_content(draft.get("content", ""))
    safe_target = _safe_text(target)
    safe_to = _safe_string_list(to)
    safe_report_type = _safe_report_type(report_type)
    attachments: list[str] = []
    project_infos: list[dict[str, object]] = []
    immediately_sign_projects: list[dict[str, object]] = []
    package = {
        "action": "create_report",
        "requires_confirmation": True,
        "confirmed": False,
        "report_type": safe_report_type,
        "target": safe_target,
        "content": content,
        "content_preview": content[:240],
        "content_length": len(content),
        "to": safe_to,
        "send_to_count": len(safe_to),
        "attachments": attachments,
        "attachments_count": len(attachments),
        "project_infos": project_infos,
        "project_infos_count": len(project_infos),
        "immediately_sign_projects": immediately_sign_projects,
        "immediately_sign_projects_count": len(immediately_sign_projects),
        "mutation": "createReport",
    }
    package["package_signature"] = _sign_confirmation_package(package)
    return package


def create_report_after_confirmation(
    *,
    confirmation_package: Mapping[str, object],
    confirmation_text: str,
    transport: ReportWriteTransport,
) -> dict[str, object]:
    content = _safe_content(confirmation_package.get("content", ""))
    if confirmation_text not in CONFIRMATION_TEXTS:
        return _error_result(
            reason="confirmation_required",
            fallback_content=content,
            mutation_used=False,
        )
    report_type = confirmation_package.get("report_type")
    if not _valid_confirmation_package(confirmation_package) or confirmation_text != REPORT_TYPE_CONFIRMATION_TEXTS.get(report_type):
        return _error_result(reason="confirmation_mismatch", fallback_content=content, mutation_used=False)

    try:
        operation = build_create_report_mutation(
            content=content,
            report_type=str(report_type),
            target=str(confirmation_package.get("target", "")),
            to=_string_list(confirmation_package.get("to", [])),
            attachments=_string_list(confirmation_package.get("attachments", [])),
            project_infos=_mapping_list(confirmation_package.get("project_infos", [])),
            immediately_sign_projects=_mapping_list(confirmation_package.get("immediately_sign_projects", [])),
        )
        response = transport.execute(operation.operation_name, operation.query, dict(operation.variables))
    except GraphQLContractError:
        return _error_result(reason="confirmation_mismatch", fallback_content=content, mutation_used=False)
    except Exception:
        return _error_result(reason="write_failed", fallback_content=content, mutation_used=True)

    transport_error = getattr(transport, "transport_error_category", None)
    http_status = getattr(transport, "http_status_category", None)
    status_code = getattr(transport, "status_code_category", None)
    if transport_error or http_status not in (None, "success") or status_code not in (None, "2xx"):
        reason = (
            "write_permission_denied"
            if http_status == "unauthorized_or_forbidden" or status_code in {"401", "403", "4xx"}
            else "write_failed"
        )
        return _error_result(reason=reason, fallback_content=content, mutation_used=True)

    if not isinstance(response, Mapping):
        return _error_result(reason="write_failed", fallback_content=content, mutation_used=True)

    if response.get("errors"):
        return _error_result(reason="write_failed", fallback_content=content, mutation_used=True)

    report = response.get("data", {}).get("createReport") if isinstance(response.get("data"), dict) else None
    if not isinstance(report, dict):
        return _error_result(reason="write_failed", fallback_content=content, mutation_used=True)

    report_id = report.get("id")
    if not report_id:
        return _error_result(reason="write_failed", fallback_content=content, mutation_used=True)

    return {
        "status": "OK",
        "reason": "ok",
        "mutation": "createReport",
        "report_id": _safe_text(report_id),
        "report_type": _safe_text(report.get("type", confirmation_package.get("report_type"))),
        "target": _safe_text(report.get("target", confirmation_package.get("target"))),
        "mutation_used": True,
        "errors": [],
    }


def _error_result(*, reason: str, fallback_content: str, mutation_used: bool) -> dict[str, object]:
    return {
        "status": "ERROR",
        "reason": reason,
        "mutation": "createReport",
        "mutation_used": mutation_used,
        "fallback_content": fallback_content,
        "errors": sanitize_errors([reason]),
    }


def _safe_content(value: object) -> str:
    sanitized = sanitize_transport_detail(value)
    return sanitized if isinstance(sanitized, str) else REDACTED_STRUCTURED_DETAIL


def _safe_text(value: object) -> str:
    sanitized = sanitize_transport_detail(value)
    return sanitized if isinstance(sanitized, str) else REDACTED_STRUCTURED_DETAIL


def _safe_report_type(value: object) -> str:
    return value if isinstance(value, str) and value in REPORT_TYPE_CONFIRMATION_TEXTS else "daily"


def _valid_confirmation_package(confirmation_package: Mapping[str, object]) -> bool:
    content = str(confirmation_package.get("content", ""))
    to = _string_list(confirmation_package.get("to", []))
    attachments = _string_list(confirmation_package.get("attachments", []))
    project_infos = _mapping_list(confirmation_package.get("project_infos", []))
    immediately_sign_projects = _mapping_list(confirmation_package.get("immediately_sign_projects", []))
    return (
        confirmation_package.get("action") == "create_report"
        and confirmation_package.get("requires_confirmation") is True
        and confirmation_package.get("confirmed") is False
        and confirmation_package.get("mutation") == "createReport"
        and confirmation_package.get("report_type") in {"daily", "weekly"}
        and confirmation_package.get("content_length") == len(content)
        and confirmation_package.get("content_preview") == content[:240]
        and confirmation_package.get("send_to_count") == len(to)
        and confirmation_package.get("attachments_count") == len(attachments)
        and confirmation_package.get("project_infos_count") == len(project_infos)
        and confirmation_package.get("immediately_sign_projects_count") == len(immediately_sign_projects)
        and _valid_package_signature(confirmation_package)
    )


def _valid_package_signature(confirmation_package: Mapping[str, object]) -> bool:
    package_signature = confirmation_package.get("package_signature")
    if not isinstance(package_signature, str):
        return False
    expected_signature = _sign_confirmation_package(confirmation_package)
    return hmac.compare_digest(package_signature, expected_signature)


def _sign_confirmation_package(confirmation_package: Mapping[str, object]) -> str:
    payload = _signature_payload(confirmation_package)
    encoded_payload = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_PACKAGE_SIGNATURE_SECRET, encoded_payload, hashlib.sha256).hexdigest()


def _signature_payload(confirmation_package: Mapping[str, object]) -> dict[str, object]:
    content = str(confirmation_package.get("content", ""))
    to = _string_list(confirmation_package.get("to", []))
    attachments = _string_list(confirmation_package.get("attachments", []))
    project_infos = _mapping_list(confirmation_package.get("project_infos", []))
    immediately_sign_projects = _mapping_list(confirmation_package.get("immediately_sign_projects", []))
    return {
        "action": confirmation_package.get("action"),
        "requires_confirmation": confirmation_package.get("requires_confirmation"),
        "confirmed": confirmation_package.get("confirmed"),
        "report_type": confirmation_package.get("report_type"),
        "target": confirmation_package.get("target"),
        "content": content,
        "content_preview": content[:240],
        "content_length": len(content),
        "to": to,
        "send_to_count": len(to),
        "attachments": attachments,
        "attachments_count": len(attachments),
        "project_infos": project_infos,
        "project_infos_count": len(project_infos),
        "immediately_sign_projects": immediately_sign_projects,
        "immediately_sign_projects_count": len(immediately_sign_projects),
        "mutation": confirmation_package.get("mutation"),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _safe_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [safe_item for item in value if (safe_item := _safe_text(item))]


def _mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]
