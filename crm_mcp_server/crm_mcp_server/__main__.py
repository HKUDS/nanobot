"""CRM MCP server module entrypoint."""

from __future__ import annotations

import argparse
import json
import sys

from crm_mcp_server.server import SERVER_NAME
from crm_mcp_server.stdio_server import mcp_tool_payloads, run_stdio_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CRM MCP server")
    parser.add_argument("--metadata", action="store_true")
    args = parser.parse_args([] if argv is None else argv)
    if args.metadata:
        tools = [str(payload["name"]) for payload in mcp_tool_payloads()]
        print(json.dumps({"name": SERVER_NAME, "tools": tools}, sort_keys=True))
        return 0
    run_stdio_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
