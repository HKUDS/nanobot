# MCP Server (Optional)

If your agent supports MCP and you'd prefer tool-based access instead of HTTP requests, you can add the Nightmarket MCP server. This is entirely optional — the HTTP API works everywhere.

## Setup

Add to your agent's MCP config (`.claude/mcp.json`, `.cursor/mcp.json`, etc.):

```json
{
  "nightmarket": {
    "command": "npx",
    "args": ["-y", "nightmarket-mcp"],
    "env": {
      "WALLET_KEY": "<your-wallet-private-key>"
    }
  }
}
```

Get a wallet key from https://crowpay.ai or use your own funded with USDC on Base.

## Tools

### browse_services

Search for available APIs.

- `search` (string, optional) — filter by name, description, or seller

### get_service_details

Get full docs for a service.

- `endpoint_id` (string, required) — the ID from browse_services

Returns: name, seller, method, price, total calls, proxy URL, description, request/response examples.

### call_service

Call an API with automatic payment.

- `endpoint_id` (string, required) — the endpoint to call
- `method` (string, optional) — GET, POST, PUT, PATCH, DELETE (default: GET)
- `body` (string, optional) — request body for POST/PUT/PATCH
- `headers` (object, optional) — additional HTTP headers

Returns the API response. Payment is handled automatically using WALLET_KEY.
