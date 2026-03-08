"""MCP server that exposes Paperclip API operations as tools.

Run as a stdio MCP server:
    nanobot-mcp-paperclip

Configure in nanobot's config.yaml:
    tools:
      mcp_servers:
        paperclip:
          command: nanobot-mcp-paperclip
          env:
            PAPERCLIP_URL: "http://localhost:3000"
            PAPERCLIP_TOKEN: "<agent-api-token>"
            PAPERCLIP_COMPANY_ID: "<company-id>"
            PAPERCLIP_AGENT_ID: "<this-agent-id>"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from nanobot_mcp_paperclip.client import PaperclipClient

# ── configuration ────────────────────────────────────────────────────

PAPERCLIP_URL = os.environ.get("PAPERCLIP_URL", "http://localhost:3000")
PAPERCLIP_TOKEN = os.environ.get("PAPERCLIP_TOKEN", "")
PAPERCLIP_COMPANY_ID = os.environ.get("PAPERCLIP_COMPANY_ID", "")
PAPERCLIP_AGENT_ID = os.environ.get("PAPERCLIP_AGENT_ID", "")

# ── tool definitions ─────────────────────────────────────────────────

TOOLS: list[Tool] = [
    # ── issues ───────────────────────────────────────────────────
    Tool(
        name="paperclip_create_issue",
        description=(
            "Create a new issue in Paperclip. Use for bug reports, feature requests, "
            "tasks, incidents, or any trackable work item."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue title"},
                "description": {
                    "type": "string",
                    "description": "Detailed description",
                    "default": "",
                },
                "priority": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "default": "medium",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project to associate with (optional)",
                },
                "assignee_agent_id": {
                    "type": "string",
                    "description": "Agent ID to assign to (optional)",
                },
            },
            "required": ["title"],
        },
    ),
    Tool(
        name="paperclip_list_issues",
        description="List issues in the company. Filter by status, priority, or assignee.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["backlog", "in_progress", "done", "cancelled"],
                },
                "priority": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                },
                "assignee_agent_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    Tool(
        name="paperclip_get_issue",
        description="Get full details of a specific issue by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "Issue ID"},
            },
            "required": ["issue_id"],
        },
    ),
    Tool(
        name="paperclip_update_issue",
        description="Update an issue's fields (status, priority, assignee, description, etc.).",
        inputSchema={
            "type": "object",
            "properties": {
                "issue_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["backlog", "in_progress", "done", "cancelled"],
                },
                "priority": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                },
                "assignee_agent_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["issue_id"],
        },
    ),
    Tool(
        name="paperclip_comment_on_issue",
        description="Add a comment to an issue. Use for status updates, findings, or discussion.",
        inputSchema={
            "type": "object",
            "properties": {
                "issue_id": {"type": "string"},
                "text": {"type": "string", "description": "Comment text"},
            },
            "required": ["issue_id", "text"],
        },
    ),
    # ── agents ───────────────────────────────────────────────────
    Tool(
        name="paperclip_list_agents",
        description=(
            "List all agents in the company. Returns name, role, status, "
            "adapter type, and capabilities for each agent."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="paperclip_get_agent",
        description="Get detailed info about a specific agent.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
            },
            "required": ["agent_id"],
        },
    ),
    Tool(
        name="paperclip_wake_agent",
        description=(
            "Wake another agent to assign it work. Use to delegate tasks "
            "to agents with specific capabilities (e.g., coding, devops)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent to wake"},
                "reason": {"type": "string", "description": "Why this agent is being woken"},
                "payload": {
                    "type": "object",
                    "description": "Context/data to pass to the agent",
                },
            },
            "required": ["agent_id"],
        },
    ),
    # ── costs ────────────────────────────────────────────────────
    Tool(
        name="paperclip_report_cost",
        description="Report an LLM usage cost event to Paperclip for billing and tracking.",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Model used (e.g., claude-opus-4-6)"},
                "provider": {"type": "string", "description": "Provider (e.g., anthropic)"},
                "input_tokens": {"type": "integer"},
                "output_tokens": {"type": "integer"},
                "cost_cents": {
                    "type": "integer",
                    "description": "Cost in cents (e.g., 150 = $1.50)",
                },
                "issue_id": {"type": "string", "description": "Related issue (optional)"},
                "project_id": {"type": "string", "description": "Related project (optional)"},
            },
            "required": ["model", "provider", "input_tokens", "output_tokens", "cost_cents"],
        },
    ),
    Tool(
        name="paperclip_cost_summary",
        description="Get cost summary for the company, optionally filtered by date range.",
        inputSchema={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)",
                },
            },
        },
    ),
    Tool(
        name="paperclip_cost_by_agent",
        description="Get cost breakdown by agent, optionally filtered by date range.",
        inputSchema={
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
        },
    ),
    # ── projects & goals ─────────────────────────────────────────
    Tool(
        name="paperclip_list_projects",
        description="List all projects in the company.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="paperclip_list_goals",
        description="List company goals. Goals provide strategic context for prioritizing work.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="paperclip_create_goal",
        description="Create a company goal.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "priority": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "default": "medium",
                },
            },
            "required": ["title"],
        },
    ),
    # ── approvals ────────────────────────────────────────────────
    Tool(
        name="paperclip_list_approvals",
        description="List pending and recent approvals.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="paperclip_create_approval",
        description="Request an approval (e.g., budget, deploy, access).",
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Approval type (e.g., budget, deploy, access)",
                },
                "description": {"type": "string"},
            },
            "required": ["type"],
        },
    ),
    # ── activity ─────────────────────────────────────────────────
    Tool(
        name="paperclip_activity",
        description="Get recent activity log for the company.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    # ── identity ─────────────────────────────────────────────────
    Tool(
        name="paperclip_whoami",
        description=(
            "Get this agent's identity, role, and status in Paperclip. "
            "Returns agent_id, company_id, name, role, and current configuration."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]

# ── tool dispatch ────────────────────────────────────────────────────


def _fmt(data: Any) -> list[TextContent]:
    """Format a response as JSON text content."""
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


async def _dispatch(client: PaperclipClient, name: str, args: dict[str, Any]) -> list[TextContent]:
    """Route a tool call to the appropriate client method."""

    match name:
        # issues
        case "paperclip_create_issue":
            result = await client.create_issue(
                title=args["title"],
                description=args.get("description", ""),
                priority=args.get("priority", "medium"),
                labels=args.get("labels"),
                project_id=args.get("project_id"),
                assignee_agent_id=args.get("assignee_agent_id"),
            )
            return _fmt(result)

        case "paperclip_list_issues":
            result = await client.list_issues(
                status=args.get("status"),
                priority=args.get("priority"),
                assignee_agent_id=args.get("assignee_agent_id"),
                limit=args.get("limit", 20),
            )
            return _fmt(result)

        case "paperclip_get_issue":
            result = await client.get_issue(args["issue_id"])
            return _fmt(result)

        case "paperclip_update_issue":
            issue_id = args.pop("issue_id")
            result = await client.update_issue(issue_id, **args)
            return _fmt(result)

        case "paperclip_comment_on_issue":
            result = await client.add_comment(args["issue_id"], args["text"])
            return _fmt(result)

        # agents
        case "paperclip_list_agents":
            result = await client.list_agents()
            return _fmt(result)

        case "paperclip_get_agent":
            result = await client.get_agent(args["agent_id"])
            return _fmt(result)

        case "paperclip_wake_agent":
            result = await client.wake_agent(
                args["agent_id"],
                reason=args.get("reason"),
                payload=args.get("payload"),
            )
            return _fmt(result)

        # costs
        case "paperclip_report_cost":
            result = await client.report_cost(
                agent_id=PAPERCLIP_AGENT_ID,
                model=args["model"],
                provider=args["provider"],
                input_tokens=args["input_tokens"],
                output_tokens=args["output_tokens"],
                cost_cents=args["cost_cents"],
                issue_id=args.get("issue_id"),
                project_id=args.get("project_id"),
            )
            return _fmt(result)

        case "paperclip_cost_summary":
            result = await client.cost_summary(
                start_date=args.get("start_date"),
                end_date=args.get("end_date"),
            )
            return _fmt(result)

        case "paperclip_cost_by_agent":
            result = await client.cost_by_agent(
                start_date=args.get("start_date"),
                end_date=args.get("end_date"),
            )
            return _fmt(result)

        # projects & goals
        case "paperclip_list_projects":
            return _fmt(await client.list_projects())

        case "paperclip_list_goals":
            return _fmt(await client.list_goals())

        case "paperclip_create_goal":
            result = await client.create_goal(
                title=args["title"],
                description=args.get("description", ""),
                priority=args.get("priority", "medium"),
            )
            return _fmt(result)

        # approvals
        case "paperclip_list_approvals":
            return _fmt(await client.list_approvals())

        case "paperclip_create_approval":
            type_ = args.pop("type")
            result = await client.create_approval(type_=type_, **args)
            return _fmt(result)

        # activity
        case "paperclip_activity":
            result = await client.activity(limit=args.get("limit", 20))
            return _fmt(result)

        # identity
        case "paperclip_whoami":
            if not PAPERCLIP_AGENT_ID:
                return _fmt({"error": "PAPERCLIP_AGENT_ID not configured"})
            agent = await client.get_agent(PAPERCLIP_AGENT_ID)
            agent["company_id"] = PAPERCLIP_COMPANY_ID
            return _fmt(agent)

        case _:
            return _fmt({"error": f"Unknown tool: {name}"})


# ── server setup ─────────────────────────────────────────────────────


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    if not PAPERCLIP_TOKEN:
        print("ERROR: PAPERCLIP_TOKEN environment variable is required", file=sys.stderr)
        sys.exit(1)
    if not PAPERCLIP_COMPANY_ID:
        print("ERROR: PAPERCLIP_COMPANY_ID environment variable is required", file=sys.stderr)
        sys.exit(1)

    server = Server("nanobot-mcp-paperclip")
    client = PaperclipClient(PAPERCLIP_URL, PAPERCLIP_TOKEN, PAPERCLIP_COMPANY_ID)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            return await _dispatch(client, name, arguments)
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            return _fmt({"error": f"HTTP {exc.response.status_code}", "detail": body})
        except httpx.ConnectError:
            return _fmt({"error": "Cannot connect to Paperclip", "url": PAPERCLIP_URL})
        except Exception as exc:
            return _fmt({"error": str(exc)})

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
        await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
