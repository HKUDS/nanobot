"""MCP stdio adapter for CRM report assistant tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping

from crm_mcp_server.redaction import sanitize_errors
from crm_mcp_server.report_context import REDACTED_TRANSPORT_DETAIL, sanitize_transport_detail
from crm_mcp_server.tool_runtime import call_tool, list_tool_definitions

LOG_GRAPHQL_OPERATION_PATTERN = re.compile(
    r"\b(?:query|mutation|subscription)\b\s*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*\s*)?"
    r"(?:\([^{}]*\)\s*)?\{",
    re.IGNORECASE,
)
LOG_RECORD_FACTORY_MARKER = "_crm_transport_detail_log_record_factory"


def _sanitize_transport_detail_log_record(record: logging.LogRecord) -> None:
    message = record.getMessage()
    sanitized = sanitize_transport_detail(message)
    if sanitized == message and LOG_GRAPHQL_OPERATION_PATTERN.search(message):
        sanitized = REDACTED_TRANSPORT_DETAIL
    if isinstance(sanitized, str):
        record.msg = sanitized
        record.args = ()
    if record.exc_info:
        record.exc_info = None
        record.exc_text = None


class TransportDetailLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        _sanitize_transport_detail_log_record(record)
        return True


def _add_transport_detail_log_filter_once(filters: list[logging.Filter]) -> None:
    if not any(isinstance(item, TransportDetailLogFilter) for item in filters):
        filters.append(TransportDetailLogFilter())


def _install_transport_detail_log_record_factory_once() -> None:
    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, LOG_RECORD_FACTORY_MARKER, False):
        return

    def transport_detail_log_record_factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = current_factory(*args, **kwargs)
        _sanitize_transport_detail_log_record(record)
        return record

    setattr(transport_detail_log_record_factory, LOG_RECORD_FACTORY_MARKER, True)
    logging.setLogRecordFactory(transport_detail_log_record_factory)


def install_transport_detail_log_filter() -> None:
    _install_transport_detail_log_record_factory_once()
    root_logger = logging.getLogger()
    _add_transport_detail_log_filter_once(root_logger.filters)
    for handler in root_logger.handlers:
        _add_transport_detail_log_filter_once(handler.filters)


def mcp_tool_payloads() -> list[dict[str, object]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in list_tool_definitions()
    ]


def normalize_tool_arguments(arguments: object) -> Mapping[str, object]:
    return arguments if isinstance(arguments, Mapping) else {}


def call_tool_as_json_text(name: str, arguments: object = None) -> str:
    try:
        result = call_tool(name, normalize_tool_arguments(arguments))
    except Exception:
        result = {
            "status": "ERROR",
            "reason": "internal_error",
            "errors": sanitize_errors(["internal_error"]),
        }
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


async def run_stdio_server_async() -> None:
    install_transport_detail_log_filter()

    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    server = Server("crm-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(**payload) for payload in mcp_tool_payloads()]

    @server.call_tool(validate_input=False)
    async def call_registered_tool(name: str, arguments: object) -> list[TextContent]:
        return [TextContent(type="text", text=call_tool_as_json_text(name, arguments))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_stdio_server() -> None:
    asyncio.run(run_stdio_server_async())
