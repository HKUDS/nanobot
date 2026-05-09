from __future__ import annotations

import io
import json
import logging
import sys
import traceback
import types


def test_mcp_tool_payloads_match_runtime_definitions():
    from crm_mcp_server.stdio_server import mcp_tool_payloads

    payloads = mcp_tool_payloads()
    names = {payload["name"] for payload in payloads}

    assert "crm_collect_sales_daily_context" in names
    assert "crm_create_report_after_confirmation" in names
    for payload in payloads:
        assert payload["description"]
        assert {schema["type"] for schema in payload["inputSchema"]["anyOf"]} == {
            "object",
            "array",
            "string",
            "number",
            "integer",
            "boolean",
            "null",
        }


def test_call_tool_as_json_text_returns_serialized_tool_result():
    from crm_mcp_server.stdio_server import call_tool_as_json_text

    text = call_tool_as_json_text(
        "crm_collect_sales_daily_context",
        {
            "window": {"start": "2026-05-09", "end": "2026-05-09"},
            "scope": {"scope_id": "sales-user-1"},
        },
    )
    result = json.loads(text)

    assert result["context_type"] == "sales_daily"
    assert result["records"]["projects"][0]["title"] == "Customer A Renewal"
    assert "Authorization" not in text
    assert "CRM_GRAPHQL_TOKEN" not in text


def test_call_tool_as_json_text_returns_sanitized_error_when_runtime_raises(monkeypatch):
    from crm_mcp_server import stdio_server

    def raise_unsafe_error(name, arguments):
        raise RuntimeError("Authorization Bearer https://crm.example mutation updateReport { id }")

    monkeypatch.setattr(stdio_server, "call_tool", raise_unsafe_error)

    text = stdio_server.call_tool_as_json_text("crm_collect_sales_daily_context", {})
    result = json.loads(text)

    assert result["status"] == "ERROR"
    assert result["reason"] == "internal_error"
    assert result["errors"] == [
        {
            "category": "internal_error",
            "message": "An internal error occurred.",
            "retryable": False,
        }
    ]
    for unsafe_marker in (
        "Authorization",
        "Bearer",
        "https://crm.example",
        "mutation updateReport",
        "{ id }",
    ):
        assert unsafe_marker not in text


def test_call_tool_as_json_text_normalizes_scalar_arguments_before_runtime_call(monkeypatch):
    from crm_mcp_server import stdio_server

    calls = []

    def record_arguments(name, arguments):
        calls.append({"name": name, "arguments": arguments})
        return {"status": "OK", "arguments": arguments}

    monkeypatch.setattr(stdio_server, "call_tool", record_arguments)

    text = stdio_server.call_tool_as_json_text("crm_collect_sales_daily_context", "mutation { updateReport { id } }")
    result = json.loads(text)

    assert result == {"status": "OK", "arguments": {}}
    assert calls == [{"name": "crm_collect_sales_daily_context", "arguments": {}}]
    assert "mutation { updateReport" not in text
    assert "updateReport { id }" not in text


def test_transport_detail_log_filter_sanitizes_unsafe_message():
    from crm_mcp_server.report_context import REDACTED_TRANSPORT_DETAIL
    from crm_mcp_server.stdio_server import TransportDetailLogFilter

    unsafe = "mutation { updateReport { id } } Authorization Bearer https://crm.example CRM_GRAPHQL_TOKEN"
    record = logging.LogRecord(
        name="mcp.shared.session",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Failed to validate request: %s",
        args=(unsafe,),
        exc_info=None,
    )

    assert TransportDetailLogFilter().filter(record) is True

    message = record.getMessage()
    assert message == REDACTED_TRANSPORT_DETAIL
    for unsafe_marker in (
        "mutation",
        "updateReport",
        "Authorization",
        "Bearer",
        "https://crm.example",
        "CRM_GRAPHQL_TOKEN",
    ):
        assert unsafe_marker not in message


def test_transport_detail_log_filter_sanitizes_embedded_scalar_graphql_message():
    from crm_mcp_server.report_context import REDACTED_TRANSPORT_DETAIL
    from crm_mcp_server.stdio_server import TransportDetailLogFilter

    record = logging.LogRecord(
        name="root",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="Message that failed validation: input_value=%r input_type=str",
        args=("mutation { updateReport { id } }",),
        exc_info=None,
    )

    assert TransportDetailLogFilter().filter(record) is True

    message = record.getMessage()
    assert message == REDACTED_TRANSPORT_DETAIL
    assert "mutation" not in message
    assert "updateReport" not in message


def test_transport_detail_log_filter_clears_unsafe_exception_info():
    from crm_mcp_server.stdio_server import TransportDetailLogFilter

    unsafe = "prefixed mutation { updateReport { id } } Authorization Bearer CRM_GRAPHQL_TOKEN"
    try:
        raise RuntimeError(unsafe)
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="root",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Failed to handle transport detail: %s",
        args=(unsafe,),
        exc_info=exc_info,
    )

    assert TransportDetailLogFilter().filter(record) is True

    formatted = logging.Formatter("%(message)s\n%(exc_text)s").format(record)
    if record.exc_info:
        formatted += "\n".join(traceback.format_exception(*record.exc_info))

    assert record.exc_info is None
    assert record.exc_text is None
    for unsafe_marker in (
        "prefixed mutation",
        "mutation { updateReport",
        "updateReport { id }",
        "Authorization",
        "Bearer",
        "CRM_GRAPHQL_TOKEN",
    ):
        assert unsafe_marker not in formatted


def test_install_transport_detail_log_filter_is_idempotent(monkeypatch):
    from crm_mcp_server.stdio_server import (
        TransportDetailLogFilter,
        install_transport_detail_log_filter,
    )

    logger = logging.getLogger()
    original_filters = list(logger.filters)
    monkeypatch.setattr(logger, "filters", [])

    install_transport_detail_log_filter()
    install_transport_detail_log_filter()

    installed_filters = [item for item in logger.filters if isinstance(item, TransportDetailLogFilter)]
    assert len(installed_filters) == 1
    assert logger.filters != original_filters


def test_install_transport_detail_log_filter_sanitizes_child_records_on_root_handlers(monkeypatch):
    from crm_mcp_server.stdio_server import (
        TransportDetailLogFilter,
        install_transport_detail_log_filter,
    )

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger()
    child_logger = logging.getLogger("mcp.shared.session.review_filter_test")
    monkeypatch.setattr(logger, "filters", [])
    monkeypatch.setattr(logger, "handlers", [handler])
    monkeypatch.setattr(logger, "level", logging.DEBUG)
    monkeypatch.setattr(child_logger, "filters", [])
    monkeypatch.setattr(child_logger, "handlers", [])
    monkeypatch.setattr(child_logger, "level", logging.DEBUG)
    monkeypatch.setattr(child_logger, "propagate", True)
    monkeypatch.setattr(child_logger, "disabled", False)

    unsafe = "Authorization Bearer https://crm.example mutation { updateReport { id } } CRM_GRAPHQL_TOKEN"
    try:
        raise RuntimeError(unsafe)
    except RuntimeError:
        exc_info = sys.exc_info()

    install_transport_detail_log_filter()
    install_transport_detail_log_filter()
    child_logger.error("Transport failed: %s", unsafe, exc_info=exc_info)

    emitted = stream.getvalue()
    assert "Authorization" not in emitted
    assert "Bearer" not in emitted
    assert "https://crm.example" not in emitted
    assert "mutation { updateReport" not in emitted
    assert "CRM_GRAPHQL_TOKEN" not in emitted
    assert len([item for item in logger.filters if isinstance(item, TransportDetailLogFilter)]) == 1
    assert len([item for item in handler.filters if isinstance(item, TransportDetailLogFilter)]) == 1


def test_install_transport_detail_log_filter_sanitizes_child_records_with_last_resort(monkeypatch):
    from crm_mcp_server.stdio_server import install_transport_detail_log_filter

    stream = io.StringIO()
    last_resort = logging.StreamHandler(stream)
    last_resort.setLevel(logging.WARNING)
    logger = logging.getLogger()
    child_logger = logging.getLogger("mcp.shared.session.review_last_resort_test")
    monkeypatch.setattr(logger, "filters", [])
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.DEBUG)
    monkeypatch.setattr(child_logger, "filters", [])
    monkeypatch.setattr(child_logger, "handlers", [])
    monkeypatch.setattr(child_logger, "level", logging.DEBUG)
    monkeypatch.setattr(child_logger, "propagate", True)
    monkeypatch.setattr(child_logger, "disabled", False)
    monkeypatch.setattr(logging, "lastResort", last_resort)

    unsafe = "Authorization Bearer https://crm.example mutation { updateReport { id } } CRM_GRAPHQL_TOKEN"
    install_transport_detail_log_filter()
    child_logger.warning("Transport failed: %s", unsafe)

    emitted = stream.getvalue()
    assert emitted
    assert "Authorization" not in emitted
    assert "Bearer" not in emitted
    assert "https://crm.example" not in emitted
    assert "mutation { updateReport" not in emitted
    assert "CRM_GRAPHQL_TOKEN" not in emitted


def test_install_transport_detail_log_filter_wraps_record_factory_once(monkeypatch):
    from crm_mcp_server.stdio_server import install_transport_detail_log_filter

    original_factory = logging.getLogRecordFactory()
    calls = []

    def tracking_factory(*args, **kwargs):
        calls.append((args, kwargs))
        return original_factory(*args, **kwargs)

    monkeypatch.setattr(logging, "_logRecordFactory", tracking_factory)

    install_transport_detail_log_filter()
    first_installed_factory = logging.getLogRecordFactory()
    install_transport_detail_log_filter()
    second_installed_factory = logging.getLogRecordFactory()

    record = logging.getLogger("mcp.shared.session.review_factory_test").makeRecord(
        "mcp.shared.session.review_factory_test",
        logging.WARNING,
        __file__,
        1,
        "Transport failed: %s",
        ("Authorization Bearer https://crm.example mutation { updateReport { id } }",),
        None,
    )

    assert first_installed_factory is second_installed_factory
    assert len(calls) == 1
    assert "Authorization" not in record.getMessage()
    assert "mutation { updateReport" not in record.getMessage()


def test_run_stdio_server_registers_call_tool_without_sdk_input_validation(monkeypatch):
    from crm_mcp_server.stdio_server import run_stdio_server_async

    registrations = []

    class FakeServer:
        def __init__(self, name):
            self.name = name

        def list_tools(self):
            def decorator(func):
                return func

            return decorator

        def call_tool(self, **kwargs):
            registrations.append(kwargs)

            def decorator(func):
                return func

            return decorator

        def create_initialization_options(self):
            return {}

        async def run(self, read_stream, write_stream, options):
            return None

    class FakeStdioServer:
        async def __aenter__(self):
            return object(), object()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    fake_mcp = types.ModuleType("mcp")
    fake_server_module = types.ModuleType("mcp.server")
    fake_server_module.Server = FakeServer
    fake_stdio_module = types.ModuleType("mcp.server.stdio")
    fake_stdio_module.stdio_server = lambda: FakeStdioServer()
    fake_types_module = types.ModuleType("mcp.types")
    fake_types_module.TextContent = lambda **kwargs: kwargs
    fake_types_module.Tool = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.stdio", fake_stdio_module)
    monkeypatch.setitem(sys.modules, "mcp.types", fake_types_module)

    import asyncio

    asyncio.run(run_stdio_server_async())

    assert registrations == [{"validate_input": False}]
