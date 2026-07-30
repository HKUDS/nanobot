# Connect Telegram to nanobot

This guide connects one Telegram bot to nanobot. Messages sent to that bot use
your normal nanobot model, tools, memory, and workspace.

## What this guide builds

- a Telegram bot created through BotFather
- the `telegram` channel enabled in nanobot
- a running nanobot gateway
- one pairing-approved Telegram account

## Prerequisites

- A working nanobot CLI reply:

```bash
nanobot agent -m "Hello!"
```

- A Telegram account.
- A bot token from `@BotFather`.

## Install nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## Connect Telegram in the WebUI

Start the WebUI:

```bash
nanobot webui
```

Open **Settings → Channels → Telegram**:

1. If Telegram support is not installed, turn on its switch and confirm the
   installation.
2. Paste the token from BotFather.
3. If the gateway cannot reach Telegram directly, expand **Advanced** and enter
   an HTTP or SOCKS proxy such as `http://127.0.0.1:7890`.
4. Save and enable Telegram.

The configuration badge appears as soon as a bot token is saved. A connection
check is separate: if Telegram is temporarily unreachable, the saved
configuration remains valid and the bot can continue working in environments
where the gateway has network access.

Saved tokens and proxy URLs are masked. A proxy entered here is used both for
the connection check and for normal Telegram traffic.

## Manual setup

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

Omitting `allowFrom` enables pairing-only mode. The first DM from a new user
gets a pairing code instead of agent access.

Telegram uses long polling by default. Webhook mode is available for public
HTTPS deployments; start with long polling for the first test.

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

Leave the gateway running while you test messages.

## Test a message

Open Telegram, DM the bot, and send:

```text
Hello from Telegram
```

The bot should reply with a pairing code. Approve it from an already trusted
surface, such as the local CLI:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Send the message again after approval. The reply should use the same model and
workspace as your local CLI check.

## Security notes

- Prefer pairing-only mode for first setup. Add `allowFrom` only when you want a
  static allowlist instead of code approval.
- Do not use `allowFrom: ["*"]` unless the bot is isolated or intentionally public.
- Rotate the BotFather token if it is pasted into logs or shared files.
- Review tool access before adding group chats or more users.

## Troubleshooting

- If the channel is not listed, run `nanobot plugins enable telegram` again in
  the same Python environment.
- If the WebUI shows a saved configuration but the live check cannot reach Telegram,
  the token is still saved. Confirm the gateway can reach `api.telegram.org`,
  or open **Advanced → Network proxy** and enter a proxy.
- If Telegram rejects the token, copy the current token from BotFather or
  regenerate it.
- If messages do not arrive, run `nanobot gateway --verbose` and confirm the
  Telegram channel is enabled.
- If a first DM returns a pairing code, that is expected. Approve the code before
  testing normal agent replies.
- If Telegram Web shows unsupported rich messages, keep `richMessages` disabled.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Configure MCP tools](./configure-mcp-tools.md)
