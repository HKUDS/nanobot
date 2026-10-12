# Connect Telegram to nanobot

This guide connects one Telegram bot to nanobot. Messages sent to that bot use your normal nanobot model, tools, memory, and workspace.

## What this guide builds

- a Telegram bot created through BotFather
- the `telegram` channel enabled in nanobot
- a running nanobot gateway
- one pairing-approved Telegram account

## Prerequisites

- A normal reply in your existing nanobot WebUI or CLI. If you have not reached that point, complete [Quick Start](../quick-start.md) first.

- A Telegram account.
- A bot token: open Telegram, find `@BotFather`, send `/newbot`, follow its name/username prompts, and copy the returned token. Keep the token private.

## Continue from your running instance

If you are already chatting in the WebUI, keep it open and continue below. It has already started the gateway. To reopen it later, use the same installation's `nanobot webui` command; there is no need to install nanobot again.

For terminal or server setup, use the manual configuration section below. Reuse the config/home and executable from your working instance. Docker users should use the [container commands](../deployment.md#docker-compose).

## Connect Telegram in the WebUI

Open **Channels → Telegram**:

1. If Telegram support is not installed, turn on its switch and confirm the installation.
2. Paste the token from BotFather.
3. If the gateway cannot reach Telegram directly, expand **Advanced** and enter an HTTP or SOCKS proxy such as `http://127.0.0.1:7890`.
4. Save and enable Telegram. For a first private setup, leave the sender allowlist empty: new senders must pair before they can use the agent. Do not set it to `*`.

The configuration badge appears as soon as a bot token is saved. A connection check is separate: if Telegram is temporarily unreachable, the saved configuration remains valid and the bot can continue working in environments where the gateway has network access.

Saved tokens and proxy URLs are masked. A proxy entered here is used both for the connection check and for normal Telegram traffic.

## Manual setup

<details>
<summary>Manual configuration</summary>

For a headless installation, install Telegram support:

```bash
nanobot plugins enable telegram
```

Then merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

Omit `proxy` when the gateway can reach Telegram directly.

Omitting `allowFrom` enables pairing-only mode. The first DM from a new user gets a pairing code instead of agent access.

Telegram uses long polling by default. Webhook mode is available for public HTTPS deployments; start with long polling for the first test.

</details>

## Apply the settings

In the WebUI, follow any restart prompt and keep the launcher running for the first test. You do not need to start another gateway. For unattended operation afterward, use [background or service mode](../cli-reference.md#gateway).

For manual config changes, restart the existing gateway through its owning terminal, `nanobot gateway restart` for background mode, or its service/container supervisor. If none is running, start `nanobot gateway` and leave it running. Run diagnostic CLI commands in a separate terminal using the same installation and config.

## Test a message

Open Telegram, DM the bot, and send:

```text
Hello from Telegram
```

The bot should reply with a pairing code. Return to the WebUI pairing prompt and enter the code from your own Telegram private chat. Do not approve codes from other people. An unapproved sender receives a code, not an agent reply.

<details>
<summary>Terminal-only pairing</summary>

In a separate local terminal, using the same instance:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Replace the example code with your actual code.

</details>

Send the message again after approval. Confirm that your private chat now receives a normal agent reply.

## Security notes

- Prefer pairing-only mode for first setup. Add `allowFrom` only when you want a static allowlist instead of code approval.
- Do not use `allowFrom: ["*"]` unless the bot is isolated or intentionally public.
- Rotate the BotFather token if it is pasted into logs or shared files.
- Review tool access before adding group chats or more users.

## Troubleshooting

- If the channel is not listed, run `nanobot plugins enable telegram` again in the same Python environment.
- If the WebUI shows a saved configuration but the live check cannot reach Telegram, the token is still saved. Confirm the gateway can reach `api.telegram.org`, or open **Advanced → Network proxy** and enter a proxy.
- If Telegram rejects the token, copy the current token from BotFather or regenerate it.
- If messages do not arrive, check the Telegram runtime status in **Channels** and the logs of the running gateway. Confirm it is enabled and can reach Telegram; do not start a second gateway to diagnose the first.
- If a first DM returns a pairing code, that is expected. Approve the code before testing normal agent replies.
- If Telegram Web shows unsupported rich messages, keep `richMessages` disabled.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Configure MCP tools](./configure-mcp-tools.md)
