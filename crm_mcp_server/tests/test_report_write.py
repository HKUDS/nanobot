from __future__ import annotations

import json
from typing import Any


class Transport:
    auth_mode = "bearer"
    http_status_category = "success"
    status_code_category = "2xx"
    transport_error_category = None

    def __init__(
        self,
        response: Any,
        *,
        http_status_category: str = "success",
        status_code_category: str = "2xx",
        transport_error_category: str | None = None,
    ):
        self.response = response
        self.http_status_category = http_status_category
        self.status_code_category = status_code_category
        self.transport_error_category = transport_error_category
        self.calls: list[dict[str, object]] = []

    def execute(self, operation_name: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append({"operation_name": operation_name, "query": query, "variables": variables})
        return self.response


class RaisingTransport(Transport):
    def execute(self, operation_name: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append({"operation_name": operation_name, "query": query, "variables": variables})
        raise RuntimeError("raw GraphQL Authorization: Bearer CRM_GRAPHQL_TOKEN secret endpoint")


def draft() -> dict[str, object]:
    return {
        "draft_type": "sales_daily",
        "content": "# 今日日报\n- Customer A Renewal follow-up",
        "requires_confirmation": True,
    }


def long_draft() -> dict[str, object]:
    return {
        "draft_type": "sales_daily",
        "content": "# 今日日报\n" + ("Customer A Renewal follow-up " * 20),
        "requires_confirmation": True,
    }


def malicious_draft() -> dict[str, object]:
    return {
        "draft_type": "sales_daily",
        "content": (
            "# 今日日报\n"
            "Customer A Renewal follow-up\n"
            "raw GraphQL mutation createReport { id }\n"
            "Authorization: Bearer CRM_GRAPHQL_TOKEN\n"
            "auth: token-secret-123\n"
            "endpoint=https://crm.example.test/graphql\n"
            "url: https://crm.example.test/report\n"
            "Cookie: session=secret-cookie"
        ),
        "requires_confirmation": True,
    }


def anonymous_graphql_draft() -> dict[str, object]:
    return {
        "draft_type": "sales_daily",
        "content": "mutation { updateReport { id } }",
        "requires_confirmation": True,
    }


def test_prepare_create_report_confirmation_does_not_call_transport():
    from crm_mcp_server.report_write import prepare_create_report_confirmation

    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    assert package["action"] == "create_report"
    assert package["requires_confirmation"] is True
    assert package["confirmed"] is False
    assert package["mutation"] == "createReport"
    assert package["content_length"] > 0
    assert_no_transport_secrets(package)


def test_prepare_create_report_confirmation_returns_full_package_shape():
    from crm_mcp_server.report_write import prepare_create_report_confirmation

    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=["user-1", "user-2"],
    )

    assert package["report_type"] == "daily"
    assert package["target"] == "2026-05-08T00:00:00Z"
    assert package["content"] == draft()["content"]
    assert package["content_preview"] == draft()["content"]
    assert package["to"] == ["user-1", "user-2"]
    assert package["send_to_count"] == 2
    assert package["attachments"] == []
    assert package["attachments_count"] == 0
    assert package["project_infos"] == []
    assert package["project_infos_count"] == 0
    assert package["immediately_sign_projects"] == []
    assert package["immediately_sign_projects_count"] == 0
    assert isinstance(package["package_signature"], str)
    assert package["package_signature"]
    assert_no_transport_secrets(package)


def test_prepare_create_report_confirmation_preview_uses_240_chars():
    from crm_mcp_server.report_write import prepare_create_report_confirmation

    content = str(long_draft()["content"])
    package = prepare_create_report_confirmation(
        draft=long_draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    assert len(content) > 240
    assert package["content_preview"] == content[:240]


def test_prepare_create_report_confirmation_sanitizes_malicious_draft_content():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=malicious_draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    assert package["content"] == "[redacted transport detail]"
    assert package["content_preview"] == "[redacted transport detail]"
    assert package["content_length"] == len("[redacted transport detail]")
    assert_no_transport_secrets(package)

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert result["status"] == "OK"
    assert transport.calls[0]["variables"]["content"] == "[redacted transport detail]"
    assert_no_transport_secrets(result)


def test_prepare_create_report_confirmation_sanitizes_anonymous_graphql_draft_content():
    from crm_mcp_server.report_write import prepare_create_report_confirmation

    package = prepare_create_report_confirmation(
        draft=anonymous_graphql_draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    serialized = json.dumps(package, sort_keys=True)

    assert package["content"] == "[redacted transport detail]"
    assert package["content_preview"] == "[redacted transport detail]"
    assert "mutation { updateReport" not in serialized
    assert "updateReport { id }" not in serialized
    assert_no_transport_secrets(package)


def test_prepare_create_report_confirmation_sanitizes_direct_target_and_recipients():
    from crm_mcp_server.report_write import prepare_create_report_confirmation

    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="https://crm.example.test/report?token=secret",
        to=["sales@example.com", "Authorization: Bearer CRM_GRAPHQL_TOKEN"],
    )
    serialized = json.dumps(package, sort_keys=True)

    assert package["target"] == "[redacted transport detail]"
    assert package["to"] == ["[redacted transport detail]", "[redacted transport detail]"]
    assert "sales@example.com" not in serialized
    assert_no_transport_secrets(package)


def test_prepare_create_report_confirmation_sanitizes_object_content_and_target():
    from crm_mcp_server.report_write import prepare_create_report_confirmation

    package = prepare_create_report_confirmation(
        draft={"content": {"token": "plain-secret", "amount_usd": "20000"}},
        report_type="daily",
        target={"token": "plain-secret", "url": "opaque"},  # type: ignore[arg-type]
        to=[],
    )
    serialized = json.dumps(package, sort_keys=True)

    assert package["content"] == "[redacted structured detail]"
    assert package["content_preview"] == "[redacted structured detail]"
    assert package["target"] == "[redacted structured detail]"
    assert "plain-secret" not in serialized
    assert "amount_usd" not in serialized
    assert "20000" not in serialized
    assert "token" not in serialized


def test_prepare_create_report_confirmation_sanitizes_bare_currency_content():
    from crm_mcp_server.report_write import prepare_create_report_confirmation

    package = prepare_create_report_confirmation(
        draft={"content": "Budget is $20,000 and fee is ¥30,000"},
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    serialized = json.dumps(package, ensure_ascii=False, sort_keys=True)

    assert "[redacted business detail]" in package["content"]
    assert "$20,000" not in serialized
    assert "¥30,000" not in serialized


def test_prepare_create_report_confirmation_normalizes_direct_report_type():
    from crm_mcp_server.report_write import prepare_create_report_confirmation

    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily Authorization Bearer CRM_GRAPHQL_TOKEN https://crm.example.test/graphql",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    serialized = json.dumps(package, sort_keys=True)

    assert package["report_type"] == "daily"
    assert "Authorization" not in serialized
    assert_no_transport_secrets(package)


def test_create_report_requires_exact_confirmation():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="看起来可以",
        transport=transport,
    )

    assert result["status"] == "ERROR"
    assert result["reason"] == "confirmation_required"
    assert transport.calls == []
    assert result["fallback_content"] == draft()["content"]
    assert result["errors"] == [
        {
            "category": "confirmation_required",
            "message": "Explicit confirmation is required before writing to CRM.",
            "retryable": False,
        }
    ]


def test_create_report_confirmation_error_sanitizes_object_fallback_content():
    from crm_mcp_server.report_write import create_report_after_confirmation

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})

    result = create_report_after_confirmation(
        confirmation_package={"content": {"token": "plain-secret", "amount_usd": "20000"}, "report_type": "daily"},
        confirmation_text="看起来可以",
        transport=transport,
    )
    serialized = json.dumps(result, sort_keys=True)

    assert result["status"] == "ERROR"
    assert result["fallback_content"] == "[redacted structured detail]"
    assert "plain-secret" not in serialized
    assert "amount_usd" not in serialized
    assert "20000" not in serialized


def test_create_report_after_confirmation_calls_only_create_report():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )
    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert result["status"] == "OK"
    assert result["report_id"] == "report-1"
    assert len(transport.calls) == 1
    assert transport.calls[0]["operation_name"] == "createReport"
    assert "mutation createReport" in transport.calls[0]["query"]
    assert "updateReport" not in transport.calls[0]["query"]
    assert transport.calls[0]["variables"]["content"] == draft()["content"]
    assert_no_transport_secrets(result)


def test_create_report_success_sanitizes_response_fields():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport(
        {
            "data": {
                "createReport": {
                    "id": "raw GraphQL mutation updateReport { id }",
                    "type": "sales@example.com",
                    "target": "https://crm.example.test/report?token=secret",
                }
            }
        }
    )
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )
    serialized = json.dumps(result, sort_keys=True)

    assert result["status"] == "OK"
    assert result["report_id"] == "[redacted transport detail]"
    assert result["report_type"] == "[redacted transport detail]"
    assert result["target"] == "[redacted transport detail]"
    assert "sales@example.com" not in serialized
    assert "updateReport" not in serialized
    assert_no_transport_secrets(result)


def test_create_report_rejects_tampered_confirmation_metadata():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    for field, value in (
        ("action", "update_report"),
        ("requires_confirmation", False),
        ("confirmed", True),
        ("report_type", "monthly"),
    ):
        transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
        package = prepare_create_report_confirmation(
            draft=draft(),
            report_type="daily",
            target="2026-05-08T00:00:00Z",
            to=[],
        )
        package[field] = value

        result = create_report_after_confirmation(
            confirmation_package=package,
            confirmation_text="确认提交这份日报",
            transport=transport,
        )

        assert_confirmation_mismatch_result(result)
        assert transport.calls == []
        assert result["fallback_content"] == draft()["content"]
        assert_no_transport_secrets(result)


def test_create_report_rejects_package_mutation_mismatch():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    package["mutation"] = "updateReport"

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_confirmation_mismatch_result(result)
    assert transport.calls == []
    assert result["fallback_content"] == draft()["content"]
    assert_no_transport_secrets(result)


def test_create_report_rejects_missing_package_signature_without_transport_call():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    del package["package_signature"]

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_confirmation_mismatch_result(result)
    assert transport.calls == []
    assert result["fallback_content"] == draft()["content"]
    assert_no_transport_secrets(result)


def test_create_report_rejects_invalid_package_signature_without_transport_call():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    package["package_signature"] = "caller-controlled-signature"

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_confirmation_mismatch_result(result)
    assert transport.calls == []
    assert result["fallback_content"] == draft()["content"]
    assert_no_transport_secrets(result)


def test_create_report_rejects_tampered_content_with_stale_signature_without_transport_call():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    package["content"] = "# Tampered daily report"
    package["content_length"] = len(str(package["content"]))
    package["content_preview"] = str(package["content"])[:240]

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_confirmation_mismatch_result(result)
    assert transport.calls == []
    assert result["fallback_content"] == "# Tampered daily report"
    assert_no_transport_secrets(result)


def test_create_report_rejects_tampered_malicious_content_with_sanitized_fallback():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    package["content"] = malicious_draft()["content"]
    package["content_length"] = len(str(package["content"]))
    package["content_preview"] = str(package["content"])[:240]

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_confirmation_mismatch_result(result)
    assert transport.calls == []
    assert result["fallback_content"] == "[redacted transport detail]"
    assert_no_transport_secrets(result)


def test_create_report_rejects_tampered_bare_graphql_content_with_sanitized_fallback():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    package["content"] = "mutation updateReport { id }"
    package["content_length"] = len(str(package["content"]))
    package["content_preview"] = str(package["content"])[:240]

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    serialized = json.dumps(result, sort_keys=True)
    assert_confirmation_mismatch_result(result)
    assert transport.calls == []
    assert result["fallback_content"] == "[redacted transport detail]"
    assert "mutation updateReport" not in serialized
    assert "updateReport { id }" not in serialized
    assert_no_transport_secrets(result)


def test_create_report_rejects_tampered_anonymous_graphql_content_with_sanitized_fallback():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )
    package["content"] = "mutation { updateReport { id } }"
    package["content_length"] = len(str(package["content"]))
    package["content_preview"] = str(package["content"])[:240]

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    serialized = json.dumps(result, sort_keys=True)
    assert_confirmation_mismatch_result(result)
    assert transport.calls == []
    assert result["fallback_content"] == "[redacted transport detail]"
    assert "mutation { updateReport" not in serialized
    assert "updateReport { id }" not in serialized
    assert_no_transport_secrets(result)


def test_create_report_rejects_tampered_derived_confirmation_metadata():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    for field, value in (
        ("content_length", 0),
        ("content_preview", "tampered preview"),
        ("send_to_count", 99),
        ("attachments_count", 1),
        ("project_infos_count", 1),
        ("immediately_sign_projects_count", 1),
    ):
        transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
        package = prepare_create_report_confirmation(
            draft=draft(),
            report_type="daily",
            target="2026-05-08T00:00:00Z",
            to=["user-1"],
        )
        package[field] = value

        result = create_report_after_confirmation(
            confirmation_package=package,
            confirmation_text="确认提交这份日报",
            transport=transport,
        )

        assert_confirmation_mismatch_result(result)
        assert transport.calls == []
        assert result["fallback_content"] == draft()["content"]
        assert_no_transport_secrets(result)


def test_create_report_binds_daily_and_weekly_confirmation_phrases_to_report_type():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "weekly", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="weekly",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_confirmation_mismatch_result(result)
    assert transport.calls == []
    assert result["fallback_content"] == draft()["content"]


def test_create_report_rejects_weekly_confirmation_phrase_for_daily_report():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份周报",
        transport=transport,
    )

    assert_confirmation_mismatch_result(result)
    assert transport.calls == []
    assert result["fallback_content"] == draft()["content"]


def test_create_report_weekly_confirmation_phrase_allows_weekly_report():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "weekly", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="weekly",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份周报",
        transport=transport,
    )

    assert result["status"] == "OK"
    assert result["report_id"] == "report-1"
    assert len(transport.calls) == 1
    assert transport.calls[0]["variables"]["type"] == "weekly"
    assert_no_transport_secrets(result)


def test_create_report_rejects_generic_confirmation_phrase_without_transport_call():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"data": {"createReport": {"id": "report-1", "type": "weekly", "target": "2026-05-08T00:00:00Z"}}})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="weekly",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认写入",
        transport=transport,
    )

    assert result["status"] == "ERROR"
    assert result["reason"] == "confirmation_required"
    assert transport.calls == []
    assert result["fallback_content"] == draft()["content"]
    assert result["errors"] == [
        {
            "category": "confirmation_required",
            "message": "Explicit confirmation is required before writing to CRM.",
            "retryable": False,
        }
    ]


def test_create_report_permission_denied_uses_sanitized_write_error():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport(
        {"data": {"createReport": {"id": "report-1", "type": "daily", "target": "2026-05-08T00:00:00Z"}}},
        http_status_category="unauthorized_or_forbidden",
        status_code_category="unknown",
    )
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_error_result(result, "write_permission_denied")
    assert result["fallback_content"] == draft()["content"]
    assert len(transport.calls) == 1
    assert_no_transport_secrets(result)


def test_create_report_graphql_errors_use_sanitized_write_failed():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport({"errors": [{"message": "raw GraphQL Authorization Bearer CRM_GRAPHQL_TOKEN"}]})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_error_result(result, "write_failed")
    assert result["fallback_content"] == draft()["content"]
    assert len(transport.calls) == 1
    assert_no_transport_secrets(result)


def test_create_report_transport_exception_uses_sanitized_write_failed():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = RaisingTransport({})
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_error_result(result, "write_failed")
    assert result["fallback_content"] == draft()["content"]
    assert len(transport.calls) == 1
    assert_no_transport_secrets(result)


def test_create_report_malformed_non_mapping_response_uses_sanitized_write_failed():
    from crm_mcp_server.report_write import (
        create_report_after_confirmation,
        prepare_create_report_confirmation,
    )

    transport = Transport(None)
    package = prepare_create_report_confirmation(
        draft=draft(),
        report_type="daily",
        target="2026-05-08T00:00:00Z",
        to=[],
    )

    result = create_report_after_confirmation(
        confirmation_package=package,
        confirmation_text="确认提交这份日报",
        transport=transport,
    )

    assert_error_result(result, "write_failed")
    assert result["fallback_content"] == draft()["content"]
    assert len(transport.calls) == 1
    assert_no_transport_secrets(result)


def assert_error_result(result: dict[str, object], reason: str) -> None:
    assert result["status"] == "ERROR"
    assert result["reason"] == reason
    assert result["mutation"] == "createReport"
    assert result["mutation_used"] is True
    assert result["errors"] == [
        {
            "category": reason,
            "message": {
                "write_permission_denied": "CRM write permission was denied.",
                "write_failed": "The CRM write failed.",
            }[reason],
            "retryable": False,
        }
    ]


def assert_confirmation_mismatch_result(result: dict[str, object]) -> None:
    assert result["status"] == "ERROR"
    assert result["reason"] == "confirmation_mismatch"
    assert result["mutation"] == "createReport"
    assert result["mutation_used"] is False
    assert result["errors"] == [
        {
            "category": "confirmation_mismatch",
            "message": "The confirmation did not match the pending CRM write.",
            "retryable": False,
        }
    ]


def assert_no_transport_secrets(result: dict[str, object]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for marker in (
        "raw GraphQL",
        "Authorization",
        "Bearer",
        "CRM_GRAPHQL_TOKEN",
        "secret endpoint",
        "token-secret-123",
        "https://crm.example.test/graphql",
        "https://crm.example.test/report",
        "secret-cookie",
    ):
        assert marker not in serialized
