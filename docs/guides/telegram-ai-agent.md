# Build a Telegram AI Agent with nanobot

This guide connects nanobot to Telegram so an allowed Telegram user can message
a self-hosted AI agent backed by your normal nanobot config, tools, memory, and
workspace.

## What this guide builds

- a Telegram bot created through BotFather
- the `telegram` channel enabled in nanobot
- a running nanobot gateway
- one test message from an allowed Telegram account

## Prerequisites

- A working nanobot CLI reply:

```bash
nanobot agent -m "Hello!"
```

- A Telegram account.
- A bot token from `@BotFather`.
- Your Telegram user ID for `allowFrom`.

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
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

Telegram uses long polling by default. Webhook mode is available for public
HTTPS deployments; start with long polling for the first test.

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

Leave the gateway running while you test messages.

## Test a message

Open Telegram, message the bot from the user in `allowFrom`, and send:

```text
Hello from Telegram
```

The reply should use the same model and workspace as your local CLI check.

## Security notes

- Keep `allowFrom` to your own user ID until the bot is stable.
- Do not use `allowFrom: ["*"]` unless the bot is isolated or intentionally
  public.
- Rotate the BotFather token if it is pasted into logs or shared files.
- Review tool access before adding group chats or more users.

## Troubleshooting

- If the channel is not listed, run `nanobot plugins enable telegram` again in
  the same Python environment.
- If messages do not arrive, run `nanobot gateway --verbose` and check the bot
  token and allowed user ID.
- If Telegram Web shows unsupported rich messages, keep `richMessages` disabled.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Configure MCP tools](./configure-mcp-tools.md)
