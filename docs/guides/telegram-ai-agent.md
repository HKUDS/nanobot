# Build a Telegram AI Agent with nanobot

This guide connects nanobot to Telegram so a paired Telegram user can message a
self-hosted AI agent backed by your normal nanobot config, tools, memory, and
workspace.

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

## Enable the Telegram channel

Install the optional channel dependency:

```bash
nanobot plugins enable telegram
```

Merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN"
    }
  }
}
```

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
- If messages do not arrive, run `nanobot gateway --verbose` and check the bot
  token.
- If a first DM returns a pairing code, that is expected. Approve the code before
  testing normal agent replies.
- If Telegram Web shows unsupported rich messages, keep `richMessages` disabled.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Configure MCP tools](./configure-mcp-tools.md)
