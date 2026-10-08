# Build a Feishu AI Agent with nanobot

This guide connects nanobot to Feishu or Lark through the `feishu` channel. The channel uses a WebSocket long connection, so the first setup does not require a public webhook URL.

## What this guide builds

- a Feishu/Lark bot app connected to nanobot
- the `feishu` channel enabled in `config.json`
- one pairing-approved Feishu or Lark user
- mention-only group behavior for first deployment

## Prerequisites

- A working local nanobot reply:

```bash
nanobot agent -m "Hello!"
```

- A Feishu or Lark account that can create or approve bot apps.
- Permission to run `nanobot gateway` continuously.

## Install nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## Enable the Feishu channel

Install the optional channel dependency:

```bash
nanobot plugins enable feishu
```

The easiest path is QR login:

```bash
nanobot channels login feishu
```

Open the printed URL or scan the QR code. nanobot writes the generated `appId`, `appSecret`, `domain`, and `enabled` fields into the active config.

In WebUI, open **Channels → Feishu** and choose **Connect** for the first bot, or **Add another assistant** below your existing assistants. Each new assistant has its own settings and sender approvals; adding one does not replace an existing bot. Cancel the QR flow to stop an unfinished authorization.

If QR login is unavailable, create a Feishu/Lark app manually and merge this shape into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "groupPolicy": "mention",
      "streaming": true,
      "domain": "feishu"
    }
  }
}
```

Omitting `allowFrom` enables pairing-only mode. A new user should DM the bot, get a pairing code, and be approved before using the bot normally.

For manual apps, enable the Bot capability, receive-message events, and Long Connection mode. If your app cannot get the `cardkit:card:write` permission, set `"streaming": false`.

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## Test a message

DM the bot first. It should return a pairing code. Approve it from a trusted local surface:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

After approval, DM the bot again or mention it in a group chat:

```text
@nanobot Hello from Feishu
```

## Security notes

- Prefer pairing-only mode for first setup. Add `allowFrom` only when you want a static allowlist.
- Keep `groupPolicy` as `"mention"` before inviting the bot into busy groups.
- Store app secrets through environment variables for deployed services.
- Review file, shell, and web tool access before adding more users.

## Troubleshooting

- If QR login is unavailable, use manual app setup from the full chat-apps reference.
- If streaming cards fail, confirm `cardkit:card:write` or set `"streaming": false`.
- If no messages arrive, check Feishu/Lark event permissions, Long Connection mode, and `nanobot gateway --verbose`.
- If a first DM returns a pairing code, approve it before testing normal replies.
- If WebUI cannot approve a pending code, check the reported error and select **Retry**. You do not need another code while the current one is valid.
- If WebUI reports that the pairing code could not be sent, the DM reached nanobot but its reply failed. Check the gateway log for the Feishu error and request ID, check that the app has permission to send messages as a bot (`im:message:send_as_bot`), and publish any permission changes. Then send another private message to retry; nanobot reuses the unexpired code. Pairing replies use plain text and do not need streaming-card permissions.
- If neither a code nor a pairing request appears, check the running gateway, the app's receive-message subscription, and which assistant you messaged. A saved App ID and App Secret mean **Configured**, not that message delivery has been tested. Do not set `allowFrom` to `*` to work around pairing failures.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [AI Agent Memory](./ai-agent-memory.md)
- [Configure MCP tools](./configure-mcp-tools.md)
