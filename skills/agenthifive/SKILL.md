---
name: agenthifive
description: "Use AgentHiFive-backed connections for protected external actions (Gmail, Calendar, Slack, etc.) with policy enforcement, approval gating, and audit."
metadata: {"nanobot":{"emoji":"🔐"}}
always: true
---

# AgentHiFive Protected Actions

You have access to AgentHiFive-backed tools for making protected external API calls. These tools enforce policy, require approval for sensitive operations, and provide an audit trail.

This skill is typically wired through NanoBot's shared `agenthifive` MCP server config. Production setups usually use AgentHiFive agent auth (`AGENTHIFIVE_AGENT_ID` + private key) so both the MCP server and NanoBot's approval poller can mint short-lived tokens at runtime.

Important distinction:
- AgentHiFive can also carry NanoBot channel traffic for supported providers.
- In this integration, vault-managed inbound/outbound messaging lives under `channels.agenthifive`, not under native `channels.telegram` / `channels.slack`.
- If the user wants the guided CLI path, send them to `nanobot setup-agenthifive` and have them choose **Configure channels**.
- If the user wants you to do it in-chat, prefer the built-in `configure_channel` tool and write the `agenthifive` channel block, then tell them to restart `nanobot gateway`.

## Available Tools

- `mcp_agenthifive_execute` — Execute an API call through AgentHiFive's vault (Model B brokered proxy)
- `mcp_agenthifive_download` — Download binary files through AgentHiFive and save them locally
- `mcp_agenthifive_list_connections` — List available AH5-backed connections and their policies
- `mcp_agenthifive_list_services` — Discover available services and action templates
- `mcp_agenthifive_get_my_capabilities` — Check your current access status
- `mcp_agenthifive_list_approvals` — List pending/resolved approval requests
- `mcp_agenthifive_request_capability` — Request access to a new service
- `mcp_agenthifive_revoke` — Revoke a connection
- `configure_channel` — Update NanoBot channel config in `config.json`

## Enabling AgentHiFive Channels

Use `configure_channel` when the user explicitly wants NanoBot to listen through AgentHiFive on a chat channel.

For Telegram:
- Set `channel="agenthifive"`
- Pass `enabled=true`
- Put AgentHiFive provider settings inside `settings`, for example:
  `{"providers": {"telegram": {"enabled": true, "allowFrom": ["8279370215"]}}}`
- After the tool succeeds, tell the user to restart `nanobot gateway`

For Slack:
- Set `channel="agenthifive"`
- Pass `enabled=true`
- Put AgentHiFive provider settings inside `settings`, for example:
  `{"providers": {"slack": {"enabled": true, "allowFrom": ["U123"]}}}`
- After the tool succeeds, tell the user to restart `nanobot gateway`

Important:
- Do not add or "fix" native `channels.telegram` when the user wants the AgentHiFive-managed channel path.
- The AgentHiFive service connection itself still needs to exist and be healthy.
- If the user only wants outbound/proactive Telegram sends through AgentHiFive, no `channels.agenthifive` config is required.

## How to Use `mcp_agenthifive_execute`

First, call `mcp_agenthifive_list_connections` to discover available connections and their IDs.

Then call `mcp_agenthifive_execute` with:
- `connectionId` — the connection UUID (from list_connections)
- `method` — HTTP method (GET, POST, PUT, DELETE, PATCH)
- `url` — the provider API URL (e.g., `https://gmail.googleapis.com/gmail/v1/users/me/messages`)
- `body` — request body (for POST/PUT/PATCH)
- `query` — query parameters (optional)
- `headers` — additional headers (optional, do NOT add Authorization — the vault handles it)

## How to Use `mcp_agenthifive_download`

Use `mcp_agenthifive_download` for any binary content:
- Gmail attachments
- Google Drive `alt=media` downloads
- OneDrive `/content` downloads
- Images, PDFs, archives, and other files

Provide:
- `connectionId` or `service`
- `url`
- optional `headers`
- optional `filename` hint

The tool saves the file locally and returns a JSON object with:
- `path`
- `filename`
- `contentType`
- `sizeBytes`

## Handling Approval-Required Responses

When `mcp_agenthifive_execute` returns `approvalRequired: true`:

1. **Tell the user** that their request needs approval from the workspace owner
2. **Include the reason** if provided in the response
3. **Wait** — the approval system will handle the rest automatically
4. **Do NOT re-submit the request with a modified body** — the vault validates that the replayed request matches the original exactly

When an approval is resolved, you will receive a message with the result:
- `[AgentHiFive] Your request was approved and executed successfully.` — the action completed
- `[AgentHiFive] Your request was denied by the workspace owner.` — the action was blocked
- `[AgentHiFive] Your approval request expired.` — resubmit if still needed

## If You Need to Re-submit

If the user asks you to retry after approval, re-submit the **exact same request** with the `approvalId` parameter set to the `approvalRequestId` from the original 202 response. Do not change the method, URL, body, query, or headers — the vault will reject any modifications.

## Common API Patterns

### Gmail
- List messages: `GET https://gmail.googleapis.com/gmail/v1/users/me/messages`
- Search messages: `GET https://gmail.googleapis.com/gmail/v1/users/me/messages?q=has:attachment`
- Read message: `GET https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}`
- Read full MIME structure: `GET https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}?format=full`
- Fetch attachment bytes: `GET https://gmail.googleapis.com/gmail/v1/users/me/messages/{messageId}/attachments/{attachmentId}`
- Send message: `POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send` (requires approval)

### Google Calendar
- List events: `GET https://www.googleapis.com/calendar/v3/calendars/primary/events`
- Create event: `POST https://www.googleapis.com/calendar/v3/calendars/primary/events` (requires approval)

### Gemini
- List models: `GET https://generativelanguage.googleapis.com/v1beta/models`
- Generate content: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`

## Gmail Attachment Workflow

When the user asks you to find an email with an attachment and download it:

1. Use `mcp_agenthifive_list_connections` and pick the Gmail connection.
2. Search Gmail with `q=has:attachment` and any user-supplied keywords.
3. Read candidate messages with `format=full` so you can inspect `payload.parts`.
4. Find MIME parts that include `filename` and `body.attachmentId`.
5. Fetch the attachment with `mcp_agenthifive_download` using:
   `https://gmail.googleapis.com/gmail/v1/users/me/messages/{messageId}/attachments/{attachmentId}`
6. Use the returned `path` as the saved attachment path.
7. If the user wants the file delivered back to them, use the `message` tool with `media=[saved_path]`.

Important:
- Prefer `mcp_agenthifive_download` over `mcp_agenthifive_execute` for attachments and other binary downloads.
- Do not claim an attachment was downloaded until the download tool returns a saved `path`.
- If a message only has inline parts and no `attachmentId`, explain that clearly instead of pretending a download exists.
