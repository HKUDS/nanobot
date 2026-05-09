from __future__ import annotations

import json

EXPECTED_STDIO_TOOLS = {
    "crm_collect_sales_daily_context",
    "crm_collect_sales_weekly_context",
    "crm_collect_presales_weekly_context",
    "crm_generate_sales_daily_draft",
    "crm_generate_sales_weekly_draft",
    "crm_generate_presales_weekly_table",
    "crm_create_report_after_confirmation",
}

LEGACY_STATIC_METADATA_TOOLS = {
    "crm_smoke_check",
    "crm_list_projects",
    "crm_list_business_chances",
    "crm_generate_daily_report_facts",
}


def assert_no_transport_details(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    forbidden = (
        "Authorization",
        "Bearer",
        "CRM_GRAPHQL_TOKEN",
        "raw GraphQL",
        "https://crm.example",
        "mutation updateReport",
    )
    for marker in forbidden:
        assert marker not in serialized


def assert_no_sensitive_business_details(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    forbidden = (
        "alice@example.test",
        "13800138000",
        "amount 20000",
        "contract value 30000",
        "30000",
        "Contact: Alice",
        "sales@example.com",
    )
    for marker in forbidden:
        assert marker not in serialized


def test_stdio_tool_definitions_are_report_assistant_only():
    from crm_mcp_server.tool_runtime import list_tool_definitions

    tools = list_tool_definitions()

    assert {tool.name for tool in tools} == EXPECTED_STDIO_TOOLS
    assert {tool.name for tool in tools}.isdisjoint(LEGACY_STATIC_METADATA_TOOLS)
    for tool in tools:
        assert tool.description
        assert {schema["type"] for schema in tool.input_schema["anyOf"]} == {
            "object",
            "array",
            "string",
            "number",
            "integer",
            "boolean",
            "null",
        }
        object_schema = tool.input_schema["anyOf"][0]
        assert object_schema["type"] == "object"
        assert isinstance(object_schema["properties"], dict)
    for tool in tools:
        if tool.name.startswith("crm_generate_"):
            object_schema = tool.input_schema["anyOf"][0]
            assert "context" in object_schema["properties"]
            assert "context" not in object_schema.get("required", [])


def test_stdio_tool_input_schemas_do_not_reject_or_inspect_caller_values():
    from crm_mcp_server.tool_runtime import list_tool_definitions

    forbidden_schema_keys = {"required", "additionalProperties", "items", "minimum", "maximum", "pattern", "format"}
    allowed_property_schema = {"description"}

    for tool in list_tool_definitions():
        schema = tool.input_schema
        assert set(schema) == {"anyOf"}
        object_schema = schema["anyOf"][0]
        assert not (forbidden_schema_keys & object_schema.keys()), tool.name
        assert object_schema == {
            "type": "object",
            "properties": object_schema["properties"],
        }
        for scalar_schema in schema["anyOf"][1:]:
            assert set(scalar_schema) == {"type"}
        for property_name, property_schema in object_schema["properties"].items():
            assert isinstance(property_name, str)
            assert isinstance(property_schema, dict)
            assert set(property_schema) <= allowed_property_schema, (tool.name, property_name)


def test_collect_sales_daily_context_tool_returns_sanitized_mock_context():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_collect_sales_daily_context",
        {
            "window": {"start": "2026-05-09", "end": "2026-05-09"},
            "scope": {"scope_id": "sales-user-1", "owner_ids": ["sales-user-1"]},
            "options": {"max_records": 3},
        },
    )

    assert result["context_type"] == "sales_daily"
    assert result["diagnostics"]["read_only"] is True
    assert result["diagnostics"]["mutation_used"] is False
    assert result["records"]["projects"][0]["title"] == "Customer A Renewal"
    assert_no_transport_details(result)


def test_collect_sales_weekly_context_tool_returns_sanitized_mock_context():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_collect_sales_weekly_context",
        {
            "window": {"start": "2026-05-04", "end": "2026-05-10"},
            "scope": {"scope_id": "sales-user-1", "owner_ids": ["sales-user-1"]},
            "options": {"max_records": 3},
        },
    )

    assert result["context_type"] == "sales_weekly"
    assert result["diagnostics"]["read_only"] is True
    assert result["diagnostics"]["mutation_used"] is False
    assert result["records"]["projects"][0]["title"] == "Customer A Renewal"
    assert_no_transport_details(result)


def test_collect_presales_weekly_context_tool_returns_sanitized_mock_context():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_collect_presales_weekly_context",
        {
            "window": {"start": "2026-05-04", "end": "2026-05-10"},
            "scope": {"scope_id": "presales-group-1", "group_ids": ["presales-group-1"]},
            "options": {"max_records": 3},
        },
    )

    assert result["context_type"] == "presales_weekly"
    assert result["diagnostics"]["read_only"] is True
    assert result["diagnostics"]["mutation_used"] is False
    assert result["records"]["leads"][0]["title"] == "Customer B Expansion"
    assert_no_transport_details(result)


def test_generate_sales_weekly_draft_tool_uses_mock_context_when_omitted():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool("crm_generate_sales_weekly_draft")

    assert result["draft_type"] == "sales_weekly"
    assert "本周工作总结" in result["content"]
    assert "下周计划" in result["content"]
    assert "Customer A Renewal" in result["content"]
    assert_no_transport_details(result)


def test_generate_sales_weekly_draft_tool_uses_supplied_empty_context_without_mock_fallback():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool("crm_generate_sales_weekly_draft", {"context": {}})

    assert result["draft_type"] == "sales_weekly"
    assert "本周工作总结" in result["content"]
    assert "下周计划" in result["content"]
    assert "Customer A Renewal" not in result["content"]
    assert_no_transport_details(result)


def test_generate_sales_weekly_draft_tool_uses_supplied_context_instead_of_mock_context():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_weekly_draft",
        {
            "context": {
                "context_type": "sales_weekly",
                "window": {"start": "2026-05-04", "end": "2026-05-10"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "Custom Enterprise Renewal",
                            "summary": "Executive alignment completed.",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert result["draft_type"] == "sales_weekly"
    assert "Custom Enterprise Renewal" in result["content"]
    assert "Customer A Renewal" not in result["content"]
    assert_no_transport_details(result)


def test_generate_sales_weekly_draft_tool_redacts_embedded_graphql_from_supplied_context():
    from crm_mcp_server.tool_runtime import call_tool

    unsafe_detail = "prefixed mutation { updateReport { id } }"

    result = call_tool(
        "crm_generate_sales_weekly_draft",
        {
            "context": {
                "context_type": "sales_weekly",
                "window": {"start": "2026-05-04", "end": "2026-05-10"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": unsafe_detail,
                            "summary": f"Weekly summary includes {unsafe_detail}",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert result["draft_type"] == "sales_weekly"
    assert "[redacted transport detail]" in result["content"]
    assert unsafe_detail not in serialized
    assert "mutation { updateReport" not in serialized
    assert "updateReport { id }" not in serialized
    assert_no_transport_details(result)


def test_generate_sales_weekly_draft_tool_redacts_sensitive_business_details_from_supplied_context():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_weekly_draft",
        {
            "context": {
                "context_type": "sales_weekly",
                "window": {"start": "2026-05-04", "end": "2026-05-10"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "Contact: Alice alice@example.test 13800138000",
                            "summary": "amount 20000 and contract value 30000 confirmed",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert result["draft_type"] == "sales_weekly"
    assert "[redacted business detail]" in result["content"]
    assert_no_sensitive_business_details(result)
    assert_no_transport_details(result)


def test_generate_sales_daily_draft_tool_redacts_multi_word_contact_details():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "Safe Project",
                            "summary": "Contact: Alice Smith from procurement.",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert "[redacted business detail]" in result["content"]
    assert "Alice" not in result["content"]
    assert "Smith" not in result["content"]
    assert "procurement" not in result["content"]


def test_generate_sales_daily_draft_tool_redacts_amount_like_scalar_formats_from_supplied_context():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "Safe Project",
                            "summary": "amount_usd=20000 contract_value=30000 合同金额=¥20,000",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert result["draft_type"] == "sales_daily"
    assert "[redacted business detail]" in result["content"]
    assert "amount_usd=20000" not in result["content"]
    assert "contract_value=30000" not in result["content"]
    assert "合同金额=¥20,000" not in result["content"]


def test_generate_sales_daily_draft_tool_redacts_bare_currency_amounts_from_supplied_context():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "Safe Project",
                            "summary": "Budget is $20,000 and fee is ¥30,000",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert "[redacted business detail]" in result["content"]
    assert "$20,000" not in result["content"]
    assert "¥30,000" not in result["content"]


def test_generate_sales_daily_draft_tool_redacts_bare_amount_like_text():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "Safe Project",
                            "summary": "Budget is 20000 and 预算 30000 金额 40000. Quote is 50000 for renewal. 报价 60000 已确认. Customer A paid 70000 last week. Support fee is 80000. Cost is 90000. Charge is 100000. Deal size is 110000.",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert "[redacted business detail]" in result["content"]
    assert "Budget is 20000" not in result["content"]
    assert "预算 30000" not in result["content"]
    assert "金额 40000" not in result["content"]
    assert "20000" not in result["content"]
    assert "30000" not in result["content"]
    assert "40000" not in result["content"]
    assert "50000" not in result["content"]
    assert "60000" not in result["content"]
    assert "70000" not in result["content"]
    assert "80000" not in result["content"]
    assert "90000" not in result["content"]
    assert "100000" not in result["content"]
    assert "110000" not in result["content"]
    assert "Quote is" not in result["content"]
    assert "报价" not in result["content"]
    assert "paid" not in result["content"]
    assert "fee is" not in result["content"]
    assert "Cost is" not in result["content"]
    assert "Charge is" not in result["content"]
    assert "Deal size is" not in result["content"]


def test_generate_sales_daily_draft_tool_redacts_unprefixed_endpoint_and_compact_phone():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "Safe Project",
                            "summary": "Call +8613800138000 through api.in.chaitin.net/crm/query",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert "[redacted transport detail]" in result["content"]
    assert "+8613800138000" not in result["content"]
    assert "api.in.chaitin.net/crm/query" not in result["content"]


def test_generate_sales_daily_draft_tool_redacts_parenthesized_and_landline_phone_formats():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "Safe Project",
                            "summary": "Call (555) 123-4567, +1 (555) 123-4567, or 020-12345678",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert "[redacted business detail]" in result["content"]
    assert "(555) 123-4567" not in result["content"]
    assert "+1 (555) 123-4567" not in result["content"]
    assert "020-12345678" not in result["content"]


def test_generate_sales_daily_draft_tool_redacts_separated_chinese_mobile_phone_formats():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "Safe Project",
                            "summary": "Call 138 0013 8000, 138-0013-8000, or 138.0013.8000 tomorrow",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert "[redacted business detail]" in result["content"]
    assert "138 0013 8000" not in result["content"]
    assert "138-0013-8000" not in result["content"]
    assert "138.0013.8000" not in result["content"]


def test_generate_sales_daily_draft_tool_redacts_bare_graphql_compact_phone_and_total_amounts():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "{ updateReport { id } }",
                            "summary": "embedded { createReport { id } }",
                        },
                        {
                            "id": "project-business",
                            "title": "Safe Project",
                            "summary": "Call 5551234567. Deal total 20000 confirmed",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert "[redacted transport detail]" in result["content"]
    assert "[redacted business detail]" in result["content"]
    assert "updateReport" not in result["content"]
    assert "createReport" not in result["content"]
    assert "5551234567" not in result["content"]
    assert "20000" not in result["content"]


def test_generate_sales_daily_draft_tool_redacts_graphql_selection_variants():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": '{ updateReport(id: "1") { id } }',
                            "summary": "{ alias: updateReport { id } } and { updateReport @include(if: true) { id } }",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert "[redacted transport detail]" in result["content"]
    assert "updateReport" not in result["content"]
    assert "alias:" not in result["content"]
    assert "@include" not in result["content"]


def test_generate_sales_daily_draft_tool_redacts_single_field_graphql_selections():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_generate_sales_daily_draft",
        {
            "context": {
                "context_type": "sales_daily",
                "window": {"start": "2026-05-09", "end": "2026-05-09"},
                "scope": {"scope_id": "custom-sales-user"},
                "records": {
                    "projects": [
                        {
                            "id": "project-custom",
                            "title": "{ updateReport }",
                            "summary": "{ createReport }",
                        }
                    ]
                },
                "source_refs": [],
                "unavailable_sources": [],
                "diagnostics": {"status": "OK", "read_only": True, "mutation_used": False},
            }
        },
    )

    assert "[redacted transport detail]" in result["content"]
    assert "updateReport" not in result["content"]
    assert "createReport" not in result["content"]


def test_create_report_tool_prepares_confirmation_without_mock_write():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_create_report_after_confirmation",
        {
            "draft": {"content": "# Daily\n- Customer A Renewal", "requires_confirmation": True},
            "report_type": "daily",
            "target": "2026-05-09T00:00:00Z",
            "to": [],
        },
    )

    assert result["action"] == "create_report"
    assert result["requires_confirmation"] is True
    assert result["confirmed"] is False
    assert result["mutation"] == "createReport"
    assert "package_signature" in result
    assert_no_transport_details(result)


def test_create_report_tool_does_not_echo_non_string_report_type_or_target():
    from crm_mcp_server.tool_runtime import call_tool

    unsafe_report_type = {
        "Authorization": "Bearer CRM_GRAPHQL_TOKEN",
        "url": "https://crm.example/token",
    }
    unsafe_target = {
        "query": "raw GraphQL mutation updateReport { id }",
        "token": "Bearer CRM_GRAPHQL_TOKEN",
    }

    result = call_tool(
        "crm_create_report_after_confirmation",
        {
            "draft": {"content": "# Daily\n- Customer A Renewal", "requires_confirmation": True},
            "report_type": unsafe_report_type,
            "target": unsafe_target,
            "to": ["sales@example.com", {"Authorization": "Bearer CRM_GRAPHQL_TOKEN"}],
        },
    )
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)

    assert result["report_type"] == "daily"
    assert result["target"] == ""
    assert result["to"] == ["[redacted transport detail]"]
    assert "{'Authorization'" not in serialized
    assert '"Authorization"' not in serialized
    assert_no_transport_details(result)


def test_create_report_tool_sanitizes_string_target_and_to_before_confirmation_package():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool(
        "crm_create_report_after_confirmation",
        {
            "draft": {"content": "# Daily\n- Customer A Renewal", "requires_confirmation": True},
            "report_type": "daily",
            "target": "mutation { updateReport { id } }",
            "to": ["sales@example.com", "Authorization: Bearer CRM_GRAPHQL_TOKEN"],
        },
    )
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)

    assert result["target"] == "[redacted transport detail]"
    assert result["to"] == ["[redacted transport detail]", "[redacted transport detail]"]
    assert "mutation { updateReport" not in serialized
    assert "updateReport { id }" not in serialized
    assert "Authorization: Bearer CRM_GRAPHQL_TOKEN" not in serialized
    assert_no_transport_details(result)


def test_create_report_tool_executes_mock_write_after_confirmation():
    from crm_mcp_server.tool_runtime import call_tool

    package = call_tool(
        "crm_create_report_after_confirmation",
        {
            "draft": {"content": "# Daily\n- Customer A Renewal", "requires_confirmation": True},
            "report_type": "daily",
            "target": "2026-05-09T00:00:00Z",
            "to": [],
        },
    )

    result = call_tool(
        "crm_create_report_after_confirmation",
        {"confirmation_package": package, "confirmation_text": "确认提交这份日报"},
    )

    assert result["status"] == "OK"
    assert result["mutation"] == "createReport"
    assert result["report_id"] == "mock-report-1"
    assert result["mutation_used"] is True
    assert_no_transport_details(result)


def test_create_report_tool_requires_confirmation_text_when_package_is_supplied():
    from crm_mcp_server.tool_runtime import call_tool

    package = call_tool(
        "crm_create_report_after_confirmation",
        {
            "draft": {"content": "# Daily\n- Customer A Renewal", "requires_confirmation": True},
            "report_type": "daily",
            "target": "2026-05-09T00:00:00Z",
            "to": [],
        },
    )

    result = call_tool(
        "crm_create_report_after_confirmation",
        {"confirmation_package": package},
    )

    assert result["status"] == "ERROR"
    assert result["reason"] == "confirmation_required"
    assert result["mutation"] == "createReport"
    assert result["mutation_used"] is False
    assert result["fallback_content"] == "# Daily\n- Customer A Renewal"
    assert_no_transport_details(result)


def test_unknown_tool_returns_sanitized_error():
    from crm_mcp_server.tool_runtime import call_tool

    result = call_tool("crm_smoke_check", {"token": "CRM_GRAPHQL_TOKEN"})

    assert result["status"] == "ERROR"
    assert result["reason"] == "unknown_tool"
    assert_no_transport_details(result)
