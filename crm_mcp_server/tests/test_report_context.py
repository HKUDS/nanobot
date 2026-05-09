from __future__ import annotations

import json


class Reader:
    def __init__(self, result: dict[str, object]):
        self.result = result
        self.calls: list[dict[str, object]] = []

    def __call__(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(request)
        return self.result


def valid_window() -> dict[str, object]:
    return {"start": "2026-05-08", "end": "2026-05-08"}


def valid_scope() -> dict[str, object]:
    return {"scope_id": "sales-user-1", "owner_ids": ["sales-user-1"], "group_ids": []}


def ok_result(kind: str, record_id: str, title: str) -> dict[str, object]:
    return {
        "records": [
            {
                "id": record_id,
                "title": title,
                "summary": f"{title} follow-up",
                "source_ref_ids": [f"src-{record_id}"],
            }
        ],
        "source_refs": [
            {
                "id": f"src-{record_id}",
                "system": "crm-graphql",
                "query": kind,
                "entity_type": kind,
                "source_id": record_id,
                "fields": ["id", "title", "summary"],
            }
        ],
        "errors": [],
    }


def error_result() -> dict[str, object]:
    return {
        "records": [],
        "source_refs": [],
        "errors": [{"category": "graphql_error", "message": "safe", "retryable": False}],
    }


def secret_result() -> dict[str, object]:
    return {
        "records": [
            {
                "id": "project-secret-1",
                "title": "Customer A Renewal",
                "summary": "Customer A renewal follow-up",
                "debug": "raw GraphQL contained Authorization: Bearer secret",
                "lowercase_graphql": "raw graphql response included credentials",
                "mixedcase_graphql": "Raw Graphql response included credentials",
                "lowercase_debug": "authorization: bearer secret",
                "mixedcase_debug": "AuthoRIZation: BeaRer secret",
                "auth_colon_debug": "auth: secret",
                "auth_equals_debug": "AuTh=secret",
                "token_colon_debug": "token: secret",
                "token_equals_debug": "ToKeN=secret",
                "crm_token_debug": "CRM token secret",
                "crm_token_lowercase_debug": "crm token secret",
                "crm_token_mixedcase_debug": "CrM ToKeN secret",
                "standalone_token_secret_debug": "token secret",
                "access_token_debug": "access token secret",
                "api_token_debug": "api token secret",
                "auth_token_debug": "auth token secret",
                "crm_token_hyphen_debug": "CRM-token secret",
                "crm_token_underscore_debug": "CRM_token secret",
                "endpoint_debug": "endpoint=https://crm.example/query",
                "url_debug": "url: https://crm.example/graphql",
                "diagnostic": "https://crm.example/debug/graphql",
                "bare_query_debug": "query listProjects { id name }",
                "bare_mutation_debug": "MuTaTiOn updateReport { id }",
                "anonymous_mutation_debug": "mutation { updateReport { id } }",
                "anonymous_subscription_debug": "subscription { reportChanged { id } }",
                "bare_subscription_debug": "subscription reportChanged { id }",
                "ordinary_business_text": "Endpoint customer workshop and URL naming discussion",
                "ordinary_query_text": "Customer query review and mutation planning discussion",
                "structured_secrets": {
                    "token": "plain-secret-1",
                    "access_token": "plain-secret-2",
                    "api_token": "plain-secret-3",
                    "auth_token": "plain-secret-4",
                    "CRM_token": "plain-secret-5",
                    "CRM-token": "plain-secret-6",
                    "authorization": "plain-secret-7",
                    "auth": "plain-secret-8",
                    "crm_graphql_token": "plain-secret-9",
                    "crm-graphql-token": "plain-secret-10",
                    "endpoint": "https://crm.example/query",
                    "url": "https://crm.example/graphql",
                    "debug_url": "opaque-debug-endpoint-id",
                    "Webhook-URL": "opaque-webhook-endpoint-id",
                    "callbackUrl": "opaque-callback-endpoint-id",
                    "business_note": "Renewal author workshop",
                },
                "nested": {"token_env": "CRM_GRAPHQL_TOKEN should not leave server"},
                "source_ref_ids": ["src-project-secret-1"],
            }
        ],
        "source_refs": [
            {
                "id": "src-project-secret-1",
                "system": "crm-graphql",
                "query": "listProject with Bearer secret",
                "entity_type": "listProject",
                "source_id": "project-secret-1",
                "fields": ["id", "Authorization"],
            }
        ],
        "errors": [],
    }


def secret_error_result() -> dict[str, object]:
    return {
        "records": [],
        "source_refs": [],
        "errors": [
            {
                "category": "graphql_error",
                "message": "raw graphql failed with access token secret and CRM-token secret",
                "retryable": False,
            }
        ],
    }


def test_collect_sales_daily_context_keeps_internal_business_names():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(ok_result("listReport", "report-1", "Yesterday Daily")),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(ok_result("listProject", "project-1", "Customer A Renewal")),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    assert result["context_type"] == "sales_daily"
    assert result["window"] == valid_window()
    assert result["diagnostics"]["status"] == "OK"
    assert result["records"]["projects"][0]["title"] == "Customer A Renewal"
    assert result["records"]["activities"][0]["title"] == "Dinner Visit"
    assert result["records"]["leads"][0]["title"] == "Scenario Lead"
    assert result["unavailable_sources"] == []
    assert_no_transport_secrets(result)


def test_collect_context_marks_dependency_errors_without_inventing_records():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(error_result()),
        "projects": Reader(error_result()),
        "activities": Reader(error_result()),
        "leads": Reader(error_result()),
        "lead_pool": Reader(error_result()),
        "scenarios": Reader(error_result()),
        "immediately_sign_projects": Reader(error_result()),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={},
        readers=readers,
    )

    assert result["diagnostics"]["status"] == "INCONCLUSIVE"
    assert result["records"] == {
        "reports": [],
        "report_related_info": [],
        "projects": [],
        "activities": [],
        "leads": [],
        "lead_pool": [],
        "scenarios": [],
        "immediately_sign_projects": [],
    }
    assert {item["source"] for item in result["unavailable_sources"]} == set(readers)
    assert_no_transport_secrets(result)


def test_collect_context_redacts_transport_details_from_reader_payloads():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(secret_error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(secret_result()),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    assert result["records"]["reports"] == []
    assert result["records"]["projects"][0]["title"] == "Customer A Renewal"
    assert result["records"]["projects"][0]["summary"] == "Customer A renewal follow-up"
    assert result["records"]["projects"][0]["diagnostic"] == "[redacted transport detail]"
    assert result["records"]["projects"][0]["bare_query_debug"] == "[redacted transport detail]"
    assert result["records"]["projects"][0]["bare_mutation_debug"] == "[redacted transport detail]"
    assert result["records"]["projects"][0]["anonymous_mutation_debug"] == "[redacted transport detail]"
    assert result["records"]["projects"][0]["anonymous_subscription_debug"] == "[redacted transport detail]"
    assert result["records"]["projects"][0]["bare_subscription_debug"] == "[redacted transport detail]"
    assert (
        result["records"]["projects"][0]["ordinary_business_text"]
        == "Endpoint customer workshop and URL naming discussion"
    )
    assert (
        result["records"]["projects"][0]["ordinary_query_text"]
        == "Customer query review and mutation planning discussion"
    )
    assert result["records"]["projects"][0]["structured_secrets"]["business_note"] == "Renewal author workshop"
    assert result["unavailable_sources"][0]["source"] == "reports"
    assert "[redacted transport detail]" in json.dumps(result, sort_keys=True)
    for index in range(1, 11):
        assert f"plain-secret-{index}" not in json.dumps(result, sort_keys=True)
    assert_no_transport_secrets(result)


def test_collect_context_redacts_camelcase_and_compound_secret_keys():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-secret-camel",
                        "title": "Safe Project",
                        "accessToken": "plain-secret-access",
                        "authToken": "plain-secret-auth",
                        "crmGraphqlToken": "plain-secret-crm",
                        "graphqlEndpoint": "opaque-internal-endpoint-id",
                        "endpointUrl": "opaque-endpoint-url",
                        "callbackURL": "opaque-callback-url",
                        "sessionCookie": "plain-secret-cookie",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted transport detail]" in serialized
    for marker in (
        "accessToken",
        "authToken",
        "crmGraphqlToken",
        "graphqlEndpoint",
        "endpointUrl",
        "callbackURL",
        "sessionCookie",
        "plain-secret-access",
        "plain-secret-auth",
        "plain-secret-crm",
        "opaque-internal-endpoint-id",
        "opaque-endpoint-url",
        "opaque-callback-url",
        "plain-secret-cookie",
    ):
        assert marker not in serialized


def test_collect_context_redacts_sensitive_business_details_from_reader_payloads():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-1",
                        "title": "Contact: Alice alice@example.test 13800138000",
                        "summary": "amount 20000 and contract value 30000 confirmed",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, sort_keys=True)
    assert "[redacted business detail]" in serialized
    assert "alice@example.test" not in serialized
    assert "13800138000" not in serialized
    assert "amount 20000" not in serialized
    assert "contract value 30000" not in serialized
    assert "30000" not in serialized
    assert "Contact: Alice" not in serialized
    assert_no_transport_secrets(result)


def test_collect_context_redacts_multi_word_contact_and_address_details():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-contact",
                        "title": "Safe Project",
                        "summary": "Contact: Alice Smith from procurement. Address: 123 Main Street Suite 8.",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted business detail]" in serialized
    assert "Alice" not in serialized
    assert "Smith" not in serialized
    assert "procurement" not in serialized
    assert "123 Main Street" not in serialized


def test_collect_context_redacts_amount_keys_and_phone_formats_from_reader_payloads():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-2",
                        "title": "Sensitive Project",
                        "amount_usd": "20000",
                        "contract_note": "合同金额：¥20,000",
                        "mobile": "+86 138 0013 8000",
                        "phone": "555-123-4567",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted business detail]" in serialized
    assert "amount_usd" not in serialized
    assert "20000" not in serialized
    assert "合同金额" not in serialized
    assert "¥20,000" not in serialized
    assert "138 0013 8000" not in serialized
    assert "555-123-4567" not in serialized
    assert_no_transport_secrets(result)


def test_collect_context_redacts_structured_budget_price_value_fields():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-structured-amount",
                        "title": "Safe Project",
                        "budget": "20000",
                        "price": 30000,
                        "value": "40000",
                        "fee": "80000",
                        "cost": "90000",
                        "charge": "100000",
                        "deal_size": "110000",
                        "deal_total": "120000",
                        "total": "130000",
                        "subtotal": "140000",
                        "quote": "150000",
                        "paid": "160000",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted business detail]" in serialized
    assert "budget" not in serialized
    assert "price" not in serialized
    assert "value" not in serialized
    assert "fee" not in serialized
    assert "cost" not in serialized
    assert "charge" not in serialized
    assert "deal_size" not in serialized
    assert "deal_total" not in serialized
    assert "total" not in serialized
    assert "subtotal" not in serialized
    assert "quote" not in serialized
    assert "paid" not in serialized
    assert "20000" not in serialized
    assert "30000" not in serialized
    assert "40000" not in serialized
    assert "80000" not in serialized
    assert "90000" not in serialized
    assert "100000" not in serialized
    assert "110000" not in serialized
    assert "120000" not in serialized
    assert "130000" not in serialized
    assert "140000" not in serialized
    assert "150000" not in serialized
    assert "160000" not in serialized


def test_collect_context_does_not_echo_non_string_window_or_scope_values():
    from crm_mcp_server.report_context import collect_sales_daily_context

    result = collect_sales_daily_context(
        window={"start": 20000, "end": 30000},
        scope={"scope_id": 40000, "owner_ids": ["sales-user-1"], "group_ids": []},
        options={},
        readers={},
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert result["window"] == {"start": "", "end": ""}
    assert result["scope"]["scope_id"] == ""
    assert "20000" not in serialized
    assert "30000" not in serialized
    assert "40000" not in serialized


def test_collect_context_redacts_amount_like_scalar_formats_from_reader_payloads():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-3",
                        "title": "Safe Project",
                        "summary": "amount_usd=20000 contract_value=30000 合同金额=¥20,000",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted business detail]" in serialized
    assert "amount_usd=20000" not in serialized
    assert "contract_value=30000" not in serialized
    assert "合同金额=¥20,000" not in serialized


def test_collect_context_redacts_bare_currency_amounts_and_endpoint_hosts():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-4",
                        "title": "Safe Project",
                        "summary": "Budget is $20,000 and fee is ¥30,000.",
                    },
                    {
                        "id": "project-sensitive-5",
                        "title": "Safe Endpoint Project",
                        "summary": "endpoint api.in.chaitin.net/crm/query url api.in.chaitin.net/crm/query",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted business detail]" in serialized
    assert "[redacted transport detail]" in serialized
    assert "$20,000" not in serialized
    assert "¥30,000" not in serialized
    assert "api.in.chaitin.net/crm/query" not in serialized


def test_collect_context_redacts_bare_amount_like_text():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-amount",
                        "title": "Safe Project",
                        "summary": "Budget is 20000 and 预算 30000 金额 40000. Quote is 50000 for renewal. 报价 60000 已确认. Customer A paid 70000 last week. Support fee is 80000. Cost is 90000. Charge is 100000. Deal size is 110000.",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted business detail]" in serialized
    assert "Budget is 20000" not in serialized
    assert "预算 30000" not in serialized
    assert "金额 40000" not in serialized
    assert "20000" not in serialized
    assert "30000" not in serialized
    assert "40000" not in serialized
    assert "50000" not in serialized
    assert "60000" not in serialized
    assert "70000" not in serialized
    assert "80000" not in serialized
    assert "90000" not in serialized
    assert "100000" not in serialized
    assert "110000" not in serialized
    assert "Quote is" not in serialized
    assert "报价" not in serialized
    assert "paid" not in serialized
    assert "fee is" not in serialized
    assert "Cost is" not in serialized
    assert "Charge is" not in serialized
    assert "Deal size is" not in serialized


def test_collect_context_redacts_unprefixed_endpoint_hosts_and_compact_international_phones():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-6",
                        "title": "Safe Project",
                        "summary": "Call +8613800138000 through api.in.chaitin.net/crm/query",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted transport detail]" in serialized
    assert "+8613800138000" not in serialized
    assert "api.in.chaitin.net/crm/query" not in serialized


def test_collect_context_redacts_parenthesized_and_landline_phone_formats():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-phone",
                        "title": "Safe Project",
                        "summary": "Call (555) 123-4567, +1 (555) 123-4567, or 020-12345678",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted business detail]" in serialized
    assert "(555) 123-4567" not in serialized
    assert "+1 (555) 123-4567" not in serialized
    assert "020-12345678" not in serialized


def test_collect_context_redacts_separated_chinese_mobile_phone_formats():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-cn-phone",
                        "title": "Safe Project",
                        "summary": "Call 138 0013 8000, 138-0013-8000, or 138.0013.8000 tomorrow",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted business detail]" in serialized
    assert "138 0013 8000" not in serialized
    assert "138-0013-8000" not in serialized
    assert "138.0013.8000" not in serialized


def test_collect_context_redacts_bare_graphql_selection_compact_phone_and_total_amounts():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-mixed",
                        "title": "{ updateReport { id } }",
                        "summary": "embedded { createReport { id } }",
                    },
                    {
                        "id": "project-sensitive-business",
                        "title": "Safe Project",
                        "summary": "Call 5551234567. Deal total 20000 confirmed",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted transport detail]" in serialized
    assert "[redacted business detail]" in serialized
    assert "updateReport" not in serialized
    assert "createReport" not in serialized
    assert "5551234567" not in serialized
    assert "20000" not in serialized


def test_collect_context_redacts_graphql_selection_variants():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-graphql-variants",
                        "title": '{ updateReport(id: "1") { id } }',
                        "summary": "{ alias: updateReport { id } } and { updateReport @include(if: true) { id } }",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted transport detail]" in serialized
    assert "updateReport" not in serialized
    assert "alias:" not in serialized
    assert "@include" not in serialized


def test_collect_context_redacts_single_field_graphql_selections():
    from crm_mcp_server.report_context import collect_sales_daily_context

    readers = {
        "reports": Reader(error_result()),
        "report_related_info": Reader(ok_result("reportRelatedInfo", "related-1", "Related Context")),
        "projects": Reader(
            {
                "records": [
                    {
                        "id": "project-sensitive-single-field-graphql",
                        "title": "{ updateReport }",
                        "summary": "{ createReport }",
                    }
                ],
                "source_refs": [],
                "errors": [],
            }
        ),
        "activities": Reader(ok_result("listActivity", "activity-1", "Dinner Visit")),
        "leads": Reader(ok_result("list_leads", "lead-1", "Scenario Lead")),
        "lead_pool": Reader(ok_result("list_leads_pool", "pool-1", "Pool Lead")),
        "scenarios": Reader(ok_result("list_opportunity_scenario", "scenario-1", "Industry Scenario")),
        "immediately_sign_projects": Reader(ok_result("listImmediatelySignProject", "sign-1", "Signing Project")),
    }

    result = collect_sales_daily_context(
        window=valid_window(),
        scope=valid_scope(),
        options={"max_records": 5},
        readers=readers,
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "[redacted transport detail]" in serialized
    assert "updateReport" not in serialized
    assert "createReport" not in serialized


def assert_no_transport_secrets(result: dict[str, object]) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for marker in (
        "raw GraphQL",
        "raw graphql",
        "Raw Graphql",
        "Authorization",
        "authorization",
        "AuthoRIZation",
        "Bearer",
        "bearer",
        "BeaRer",
        "auth:",
        "AuTh=",
        "token:",
        "ToKeN=",
        "CRM token",
        "crm token",
        "CrM ToKeN",
        "token secret",
        "access token",
        "api token",
        "auth token",
        "CRM-token",
        "CRM_token",
        "CRM_GRAPHQL_TOKEN",
        "endpoint=https://crm.example/query",
        "url: https://crm.example/graphql",
        "https://crm.example/query",
        "https://crm.example/graphql",
        "https://crm.example/debug/graphql",
        "opaque-debug-endpoint-id",
        "opaque-webhook-endpoint-id",
        "opaque-callback-endpoint-id",
    ):
        assert marker not in serialized
