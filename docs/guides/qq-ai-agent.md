# Build a QQ AI Agent with nanobot

This guide connects nanobot to QQ through the official `qq` channel. The official channel uses the botpy SDK and currently focuses on private messages. For QQ group chat and OneBot v11 workflows, use the Napcat section in the full chat-apps reference.

## What this guide builds

- a QQ bot application
- the `qq` channel enabled in nanobot
- one pairing-approved QQ private sender
- a running nanobot gateway

## Prerequisites

- A normal reply in your existing nanobot WebUI or CLI. If you have not reached that point, complete [Quick Start](../quick-start.md) first.

- Access to the QQ Open Platform.
- A QQ account added to the bot sandbox for testing.

## Continue from your running instance

If you are already chatting in the WebUI, keep it open and continue below. It has already started the gateway. To reopen it later, use the same installation's `nanobot webui` command; there is no need to install nanobot again.

For terminal or server setup, use the manual configuration section below. Reuse the config/home and executable from your working instance. Docker users should use the [container commands](../deployment.md#docker-compose).

## Enable the QQ channel

Create a QQ bot application, copy its AppID and AppSecret, and add your account to the sandbox members. In **Channels → QQ**, enter those credentials, enable the channel, and save. Follow any installation or restart prompt.

<details>
<summary>Manual configuration</summary>

Install the optional channel dependency:

```bash
nanobot plugins enable qq
```

In the QQ Open Platform, create a bot application and copy the AppID and AppSecret. Add your QQ account to the sandbox test members, then merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "msgFormat": "plain"
    }
  }
}
```

Omitting `allowFrom` enables pairing-only mode. A new private sender should get a pairing code before normal agent access.

</details>

## Apply the settings

In the WebUI, follow any restart prompt and keep the launcher running for the first test. You do not need to start another gateway. For unattended operation afterward, use [background or service mode](../cli-reference.md#gateway).

For manual config changes, restart the existing gateway through its owning terminal, `nanobot gateway restart` for background mode, or its service/container supervisor. If none is running, start `nanobot gateway` and leave it running. Run diagnostic CLI commands in a separate terminal using the same installation and config.

## Test a message

Send the QQ bot a private message from a sandbox account. It should return a pairing code. Return to the WebUI pairing prompt and enter the code from your own private chat. Only a matching pending code is approved; do not enter another person's code. Then send your message again.

<details>
<summary>Terminal-only pairing</summary>

In a separate local terminal, using the same instance:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Replace the example code with your actual code.

</details>

Send the message again after approval.

## Security notes

- Prefer pairing-only mode for first setup. Add `allowFrom` only when you want a static allowlist.
- Keep sandbox testing separate from production publishing.
- Store QQ AppSecret through environment variables for deployed services.
- Use Napcat only when you intentionally need a QQ account bridge and group chat features.

## Troubleshooting

- If private messages do not arrive, confirm the sender is in the QQ bot sandbox and the gateway is running.
- If output formatting is unreliable, keep `msgFormat` as `"plain"`.
- If a first private message returns a pairing code, approve it before testing normal replies.
- If you need QQ groups, see the Napcat section in the full chat-apps reference.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [AI Agent Memory](./ai-agent-memory.md)
- [Configure MCP tools](./configure-mcp-tools.md)
