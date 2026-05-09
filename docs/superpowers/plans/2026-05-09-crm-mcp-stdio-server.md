# CRM MCP Stdio Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `python -m crm_mcp_server` into a usable mock-mode stdio MCP server for CRM Report Assistant tools while preserving safe `--metadata` mode.

**Architecture:** Add a plain Python tool runtime registry first, then wrap it with a thin MCP SDK stdio adapter. Keep all CRM behavior mock/injected in this phase; no real CRM network access or real writeback is introduced.

**Tech Stack:** Python 3.11, `uv`, pytest, ruff, existing `mcp` Python SDK dependency from the root project when available, existing `crm_mcp_server` package.

---

## File Structure

- Create `crm_mcp_server/crm_mcp_server/tool_runtime.py`: owns tool definitions, input schemas, deterministic mock readers, mock write transport, and direct `call_tool()` dispatch.
- Create `crm_mcp_server/crm_mcp_server/stdio_server.py`: owns MCP SDK adapter and stdio serving entrypoint.
- Modify `crm_mcp_server/crm_mcp_server/__main__.py`: preserve `--metadata`; start stdio server by default.
- Modify `crm_mcp_server/pyproject.toml`: add `mcp` dependency if CRM package needs to run standalone through `uv --project crm_mcp_server`.
- Modify `docs/crm/examples/nanobot-crm-mcp.mock.yaml`: remove `--metadata` from stdio args.
- Modify `tests/config/test_crm_mcp_config.py`: expect runnable stdio args without `--metadata`.
- Modify docs: `docs/crm/MCP_CONFIGURATION.md`, `docs/crm/MANUAL_TEST.md`, `docs/crm/README.md`, and `crm_mcp_server/README.md` to reflect mock stdio serving.
- Create tests:
  - `crm_mcp_server/tests/test_tool_runtime.py`
  - `crm_mcp_server/tests/test_stdio_server.py`
  - update `crm_mcp_server/tests/test_mcp_entrypoint.py`

## Task 1: Add Tool Runtime Registry

**Files:**
- Create: `crm_mcp_server/crm_mcp_server/tool_runtime.py`
- Test: `crm_mcp_server/tests/test_tool_runtime.py`

- [ ] **Step 1: Write failing tests for tool definitions and context call**

Create `crm_mcp_server/tests/test_tool_runtime.py`:

```python
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


def test_stdio_tool_definitions_are_report_assistant_only():
    from crm_mcp_server.tool_runtime import list_tool_definitions

    tools = list_tool_definitions()

    assert {tool.name for tool in tools} == EXPECTED_STDIO_TOOLS
    for tool in tools:
        assert tool.description
        assert tool.input_schema["type"] == "object"
        assert isinstance(tool.input_schema["properties"], dict)


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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_tool_runtime.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'crm_mcp_server.tool_runtime'`.

- [ ] **Step 3: Implement minimal tool runtime definitions and mock readers**

Create `crm_mcp_server/crm_mcp_server/tool_runtime.py`:

```python
"""Mock-mode CRM MCP tool runtime for stdio serving."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from crm_mcp_server.report_context import (
    collect_presales_weekly_context,
    collect_sales_daily_context,
    collect_sales_weekly_context,
)

ToolHandler = Callable[[Mapping[str, object]], dict[str, object]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, object]
    handler: ToolHandler


OBJECT_SCHEMA: dict[str, object] = {"type": "object", "properties": {}, "additionalProperties": True}

CONTEXT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "window": {"type": "object", "additionalProperties": True},
        "scope": {"type": "object", "additionalProperties": True},
        "options": {"type": "object", "additionalProperties": True},
    },
    "additionalProperties": False,
}


def list_tool_definitions() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            name="crm_collect_sales_daily_context",
            description="Collect mock CRM context for a sales daily report.",
            input_schema=CONTEXT_SCHEMA,
            handler=_collect_sales_daily_context_tool,
        ),
        ToolDefinition(
            name="crm_collect_sales_weekly_context",
            description="Collect mock CRM context for a sales weekly report.",
            input_schema=CONTEXT_SCHEMA,
            handler=_collect_sales_weekly_context_tool,
        ),
        ToolDefinition(
            name="crm_collect_presales_weekly_context",
            description="Collect mock CRM context for a presales weekly table.",
            input_schema=CONTEXT_SCHEMA,
            handler=_collect_presales_weekly_context_tool,
        ),
        ToolDefinition(
            name="crm_generate_sales_daily_draft",
            description="Generate a sales daily report draft from CRM context.",
            input_schema=OBJECT_SCHEMA,
            handler=_placeholder_tool,
        ),
        ToolDefinition(
            name="crm_generate_sales_weekly_draft",
            description="Generate a sales weekly report draft from CRM context.",
            input_schema=OBJECT_SCHEMA,
            handler=_placeholder_tool,
        ),
        ToolDefinition(
            name="crm_generate_presales_weekly_table",
            description="Generate a presales weekly table from CRM context.",
            input_schema=OBJECT_SCHEMA,
            handler=_placeholder_tool,
        ),
        ToolDefinition(
            name="crm_create_report_after_confirmation",
            description="Prepare or execute a mock confirmation-gated CRM report write.",
            input_schema=OBJECT_SCHEMA,
            handler=_placeholder_tool,
        ),
    )


def call_tool(name: str, arguments: Mapping[str, object] | None = None) -> dict[str, object]:
    safe_arguments = arguments if isinstance(arguments, Mapping) else {}
    for tool in list_tool_definitions():
        if tool.name == name:
            return tool.handler(safe_arguments)
    return {"status": "ERROR", "reason": "unknown_tool", "tool": name}


def _collect_sales_daily_context_tool(arguments: Mapping[str, object]) -> dict[str, object]:
    return collect_sales_daily_context(
        window=_mapping(arguments.get("window")),
        scope=_mapping(arguments.get("scope")),
        options=_mapping(arguments.get("options")),
        readers=_mock_readers(),
    )


def _collect_sales_weekly_context_tool(arguments: Mapping[str, object]) -> dict[str, object]:
    return collect_sales_weekly_context(
        window=_mapping(arguments.get("window")),
        scope=_mapping(arguments.get("scope")),
        options=_mapping(arguments.get("options")),
        readers=_mock_readers(),
    )


def _collect_presales_weekly_context_tool(arguments: Mapping[str, object]) -> dict[str, object]:
    return collect_presales_weekly_context(
        window=_mapping(arguments.get("window")),
        scope=_mapping(arguments.get("scope")),
        options=_mapping(arguments.get("options")),
        readers=_mock_readers(),
    )


def _placeholder_tool(_arguments: Mapping[str, object]) -> dict[str, object]:
    return {"status": "ERROR", "reason": "not_implemented"}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mock_readers() -> dict[str, Callable[[dict[str, object]], Mapping[str, object]]]:
    return {
        "reports": _mock_reader("listReport", "report-1", "Yesterday Daily"),
        "report_related_info": _mock_reader("reportRelatedInfo", "related-1", "Related Context"),
        "projects": _mock_reader("listProject", "project-1", "Customer A Renewal"),
        "activities": _mock_reader("listActivity", "activity-1", "Dinner Visit"),
        "leads": _mock_reader("list_leads", "lead-1", "Scenario Lead"),
        "lead_pool": _mock_reader("list_leads_pool", "pool-1", "Pool Lead"),
        "scenarios": _mock_reader("list_opportunity_scenario", "scenario-1", "Industry Scenario"),
        "immediately_sign_projects": _mock_reader("listImmediatelySignProject", "sign-1", "Signing Project"),
    }


def _mock_reader(kind: str, record_id: str, title: str) -> Callable[[dict[str, object]], Mapping[str, object]]:
    def read(_request: dict[str, object]) -> Mapping[str, object]:
        return {
            "records": [{"id": record_id, "title": title, "summary": f"{title} follow-up"}],
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

    return read
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_tool_runtime.py
```

Expected: PASS.

## Task 2: Add Draft And Confirmation Tool Runtime Handlers

**Files:**
- Modify: `crm_mcp_server/crm_mcp_server/tool_runtime.py`
- Test: `crm_mcp_server/tests/test_tool_runtime.py`

- [ ] **Step 1: Add failing tests for draft and write runtime tools**

Append to `crm_mcp_server/tests/test_tool_runtime.py`:

```python
def test_generate_sales_weekly_draft_tool_uses_supplied_or_mock_context():
    from crm_mcp_server.tool_runtime import call_tool

    context = call_tool(
        "crm_collect_sales_weekly_context",
        {"window": {"start": "2026-05-04", "end": "2026-05-10"}, "scope": {"scope_id": "sales-user-1"}},
    )

    result = call_tool("crm_generate_sales_weekly_draft", {"context": context})

    assert result["draft_type"] == "sales_weekly"
    assert "本周工作总结" in result["content"]
    assert "下周计划" in result["content"]
    assert "Customer A Renewal" in result["content"]
    assert_no_transport_details(result)


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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_tool_runtime.py
```

Expected: FAIL because draft/write handlers return `not_implemented`.

- [ ] **Step 3: Implement draft and write handlers**

Update `crm_mcp_server/crm_mcp_server/tool_runtime.py` imports:

```python
from crm_mcp_server.report_drafts import (
    generate_presales_weekly_table,
    generate_sales_daily_draft,
    generate_sales_weekly_draft,
)
from crm_mcp_server.report_write import (
    create_report_after_confirmation,
    prepare_create_report_confirmation,
)
```

Replace placeholder handlers in `list_tool_definitions()`:

```python
        ToolDefinition(
            name="crm_generate_sales_daily_draft",
            description="Generate a sales daily report draft from CRM context.",
            input_schema=OBJECT_SCHEMA,
            handler=_generate_sales_daily_draft_tool,
        ),
        ToolDefinition(
            name="crm_generate_sales_weekly_draft",
            description="Generate a sales weekly report draft from CRM context.",
            input_schema=OBJECT_SCHEMA,
            handler=_generate_sales_weekly_draft_tool,
        ),
        ToolDefinition(
            name="crm_generate_presales_weekly_table",
            description="Generate a presales weekly table from CRM context.",
            input_schema=OBJECT_SCHEMA,
            handler=_generate_presales_weekly_table_tool,
        ),
        ToolDefinition(
            name="crm_create_report_after_confirmation",
            description="Prepare or execute a mock confirmation-gated CRM report write.",
            input_schema=OBJECT_SCHEMA,
            handler=_create_report_after_confirmation_tool,
        ),
```

Add handlers:

```python
class MockReportWriteTransport:
    auth_mode = "mock"
    http_status_category = "success"
    status_code_category = "2xx"
    transport_error_category = None

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute(self, operation_name: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append({"operation_name": operation_name})
        return {
            "data": {
                "createReport": {
                    "id": "mock-report-1",
                    "type": variables.get("type", "daily"),
                    "target": variables.get("target", ""),
                }
            }
        }


def _generate_sales_daily_draft_tool(arguments: Mapping[str, object]) -> dict[str, object]:
    return generate_sales_daily_draft(_context_or_mock(arguments, "sales_daily"))


def _generate_sales_weekly_draft_tool(arguments: Mapping[str, object]) -> dict[str, object]:
    return generate_sales_weekly_draft(_context_or_mock(arguments, "sales_weekly"))


def _generate_presales_weekly_table_tool(arguments: Mapping[str, object]) -> dict[str, object]:
    return generate_presales_weekly_table(_context_or_mock(arguments, "presales_weekly"))


def _create_report_after_confirmation_tool(arguments: Mapping[str, object]) -> dict[str, object]:
    confirmation_package = arguments.get("confirmation_package")
    confirmation_text = arguments.get("confirmation_text")
    if isinstance(confirmation_package, Mapping) and isinstance(confirmation_text, str):
        return create_report_after_confirmation(
            confirmation_package=confirmation_package,
            confirmation_text=confirmation_text,
            transport=MockReportWriteTransport(),
        )
    return prepare_create_report_confirmation(
        draft=_mapping(arguments.get("draft")),
        report_type=str(arguments.get("report_type", "daily")),
        target=str(arguments.get("target", "")),
        to=_string_list(arguments.get("to")),
    )


def _context_or_mock(arguments: Mapping[str, object], context_type: str) -> Mapping[str, object]:
    context = arguments.get("context")
    if isinstance(context, Mapping):
        return context
    collector = {
        "sales_daily": collect_sales_daily_context,
        "sales_weekly": collect_sales_weekly_context,
        "presales_weekly": collect_presales_weekly_context,
    }[context_type]
    return collector(window={}, scope={"scope_id": "mock-sales"}, options={}, readers=_mock_readers())


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
```

Remove `_placeholder_tool()` if no longer used.

- [ ] **Step 4: Run tool runtime tests**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_tool_runtime.py
```

Expected: PASS.

## Task 3: Add MCP Stdio Adapter

**Files:**
- Create: `crm_mcp_server/crm_mcp_server/stdio_server.py`
- Test: `crm_mcp_server/tests/test_stdio_server.py`
- Modify: `crm_mcp_server/pyproject.toml`

- [ ] **Step 1: Write failing adapter tests without starting real stdio loop**

Create `crm_mcp_server/tests/test_stdio_server.py`:

```python
from __future__ import annotations

import json


def test_mcp_tool_payloads_match_runtime_definitions():
    from crm_mcp_server.stdio_server import mcp_tool_payloads

    payloads = mcp_tool_payloads()
    names = {payload["name"] for payload in payloads}

    assert "crm_collect_sales_daily_context" in names
    assert "crm_create_report_after_confirmation" in names
    for payload in payloads:
        assert payload["description"]
        assert payload["inputSchema"]["type"] == "object"


def test_call_tool_as_json_text_returns_serialized_tool_result():
    from crm_mcp_server.stdio_server import call_tool_as_json_text

    text = call_tool_as_json_text(
        "crm_collect_sales_daily_context",
        {"window": {"start": "2026-05-09", "end": "2026-05-09"}, "scope": {"scope_id": "sales-user-1"}},
    )
    result = json.loads(text)

    assert result["context_type"] == "sales_daily"
    assert result["records"]["projects"][0]["title"] == "Customer A Renewal"
    assert "Authorization" not in text
    assert "CRM_GRAPHQL_TOKEN" not in text
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_stdio_server.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'crm_mcp_server.stdio_server'`.

- [ ] **Step 3: Add MCP package dependency for standalone CRM project**

Modify `crm_mcp_server/pyproject.toml`:

```toml
dependencies = [
    "mcp>=1.26.0,<2.0.0",
]
```

- [ ] **Step 4: Implement adapter helpers and stdio starter**

Create `crm_mcp_server/crm_mcp_server/stdio_server.py`:

```python
"""MCP stdio adapter for CRM Report Assistant mock tools."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping

from crm_mcp_server.tool_runtime import call_tool, list_tool_definitions


def mcp_tool_payloads() -> list[dict[str, object]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in list_tool_definitions()
    ]


def call_tool_as_json_text(name: str, arguments: Mapping[str, object] | None = None) -> str:
    result = call_tool(name, arguments or {})
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


async def run_stdio_server_async() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    server = Server("crm-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=payload["name"],
                description=payload["description"],
                inputSchema=payload["inputSchema"],
            )
            for payload in mcp_tool_payloads()
        ]

    @server.call_tool()
    async def call_registered_tool(name: str, arguments: dict[str, object] | None) -> list[TextContent]:
        return [TextContent(type="text", text=call_tool_as_json_text(name, arguments or {}))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_stdio_server() -> None:
    asyncio.run(run_stdio_server_async())
```

- [ ] **Step 5: Run adapter tests**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_stdio_server.py
```

Expected: PASS.

## Task 4: Update Entrypoint And Config Example

**Files:**
- Modify: `crm_mcp_server/crm_mcp_server/__main__.py`
- Modify: `crm_mcp_server/tests/test_mcp_entrypoint.py`
- Modify: `docs/crm/examples/nanobot-crm-mcp.mock.yaml`
- Modify: `tests/config/test_crm_mcp_config.py`

- [ ] **Step 1: Write failing entrypoint/config tests**

Update `crm_mcp_server/tests/test_mcp_entrypoint.py` with:

```python
def test_module_main_without_metadata_starts_stdio_server(monkeypatch):
    from crm_mcp_server import __main__

    calls: list[str] = []

    def fake_run_stdio_server() -> None:
        calls.append("started")

    monkeypatch.setattr(__main__, "run_stdio_server", fake_run_stdio_server)

    assert __main__.main([]) == 0
    assert calls == ["started"]
```

Update `tests/config/test_crm_mcp_config.py` expectations:

```python
    assert server["args"] == [
        "run",
        "--project",
        "crm_mcp_server",
        "python",
        "-m",
        "crm_mcp_server",
    ]
```

And:

```python
    assert crm_server.args == [
        "run",
        "--project",
        "crm_mcp_server",
        "python",
        "-m",
        "crm_mcp_server",
    ]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_mcp_entrypoint.py
```

Expected: FAIL because `main([])` still raises the metadata-only not-implemented error.

Root config test may be blocked by root dependencies; try:

```bash
uv run --with pytest --with pyyaml pytest tests/config/test_crm_mcp_config.py
```

Expected: FAIL if pytest starts because config still includes `--metadata`, or BLOCKED by `botocore` download.

- [ ] **Step 3: Update `__main__.py`**

Modify `crm_mcp_server/crm_mcp_server/__main__.py`:

```python
"""CRM MCP server module entrypoint."""

from __future__ import annotations

import argparse
import json
import sys

from crm_mcp_server.contract import list_v1_tools
from crm_mcp_server.server import SERVER_NAME
from crm_mcp_server.stdio_server import run_stdio_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CRM MCP server")
    parser.add_argument("--metadata", action="store_true")
    args = parser.parse_args([] if argv is None else argv)
    if args.metadata:
        print(json.dumps({"name": SERVER_NAME, "tools": list(list_v1_tools())}, sort_keys=True))
        return 0
    run_stdio_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Update mock config example**

Modify `docs/crm/examples/nanobot-crm-mcp.mock.yaml` so args are exactly:

```yaml
args:
  - run
  - --project
  - crm_mcp_server
  - python
  - -m
  - crm_mcp_server
```

Keep `enabledTools` unchanged and keep `env`/`headers` absent or empty according to the existing schema.

- [ ] **Step 5: Run entrypoint tests**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_mcp_entrypoint.py crm_mcp_server/tests/test_stdio_server.py
```

Expected: PASS.

## Task 5: Update Documentation For Mock Stdio Serving

**Files:**
- Modify: `docs/crm/MCP_CONFIGURATION.md`
- Modify: `docs/crm/MANUAL_TEST.md`
- Modify: `docs/crm/README.md`
- Modify: `crm_mcp_server/README.md`

- [ ] **Step 1: Update docs wording**

Make these exact content changes where the current docs mention metadata-only config:

In `docs/crm/MCP_CONFIGURATION.md`, current status should say:

```md
- The CRM MCP Server starts a mock-mode stdio MCP server with `python -m crm_mcp_server`.
- `python -m crm_mcp_server --metadata` remains available for safe inspection.
- The stdio server exposes report-assistant mock tools only; it does not connect to real CRM and does not perform real CRM writes.
```

Update the status note below the stdio YAML example to:

```md
Status note: this example starts the mock-mode CRM MCP stdio server. It does not configure real CRM endpoint, token, headers, or real writeback.
```

In `docs/crm/MANUAL_TEST.md`, replace metadata-only wording with mock stdio wording:

```md
The checked-in stdio mock example is `docs/crm/examples/nanobot-crm-mcp.mock.yaml`. It runs `python -m crm_mcp_server` as a mock-mode stdio MCP server. Use `python -m crm_mcp_server --metadata` only for safe metadata inspection.
```

In `docs/crm/README.md`, current MCP status should say the mock-mode config starts the CRM MCP stdio server and does not require CRM credentials.

In `crm_mcp_server/README.md`, add a usage section:

```md
## Mock Stdio Usage

Safe metadata inspection:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server --metadata
```

Mock stdio MCP server:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server
```

The stdio server exposes mock CRM Report Assistant tools only. It does not connect to real CRM and does not perform real CRM writes.
```
```

- [ ] **Step 2: Run CRM tests and lint**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests
uv run --project crm_mcp_server --with ruff ruff check crm_mcp_server tests/config/test_crm_mcp_config.py
```

Expected: PASS.

## Task 6: Full Verification And Final Review

**Files:**
- No new files unless verification exposes a focused fix.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_tool_runtime.py crm_mcp_server/tests/test_stdio_server.py crm_mcp_server/tests/test_mcp_entrypoint.py
```

Expected: PASS.

- [ ] **Step 2: Run full CRM package tests**

Run:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run:

```bash
uv run --project crm_mcp_server --with ruff ruff check crm_mcp_server tests/config/test_crm_mcp_config.py
```

Expected: `All checks passed!`

- [ ] **Step 4: Run metadata smoke**

Run:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server --metadata
```

Expected: JSON includes `crm_collect_sales_daily_context` and `crm_create_report_after_confirmation`, and contains no endpoint/token/auth header/raw GraphQL details.

- [ ] **Step 5: Try root config test**

Run:

```bash
uv run --with pytest --with pyyaml pytest tests/config/test_crm_mcp_config.py
```

Expected: PASS if root dependencies resolve. If it times out while downloading `botocore` before pytest starts, record as an environment verification gap.

- [ ] **Step 6: Review final diff safety**

Run:

```bash
git diff -- crm_mcp_server docs/crm tests/config/test_crm_mcp_config.py
```

Expected findings:

- `--metadata` mode remains available.
- Mock config starts stdio server without endpoint/token/header values.
- No real CRM network access is introduced.
- No real `createReport` write is introduced.
- Tool outputs are JSON text and sanitized.
- Rust is not introduced.

## Self-Review

Spec coverage:

- Real stdio MCP serving: Tasks 3 and 4.
- Metadata preservation: Task 4 and Task 6.
- Tool runtime registry: Tasks 1 and 2.
- Mock context/draft/write flows: Tasks 1 and 2.
- Config update away from metadata-only: Task 4.
- Docs update: Task 5.
- Rust decision: design-only, no implementation task by scope.

Placeholder scan:

- No task contains TBD, TODO, or undefined implementation instructions.
- Every code-changing step includes concrete file paths, code snippets, and commands.

Type consistency:

- `ToolDefinition.name`, `description`, `input_schema`, and `handler` are used consistently by `tool_runtime.py` and `stdio_server.py`.
- `call_tool_as_json_text()` serializes `call_tool()` dictionaries and is used by MCP adapter tests.
- Config arg expectations match the YAML command shape.
