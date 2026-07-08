# Build a Discord AI Agent with nanobot

This guide connects nanobot to Discord so a Discord user or server channel can
talk to your self-hosted AI agent through the nanobot gateway.

## What this guide builds

- a Discord bot application
- Message Content intent enabled
- the `discord` channel enabled in nanobot
- one direct message or mention test

## Prerequisites

- A working local nanobot reply:

```bash
nanobot agent -m "Hello!"
```

- Access to the Discord Developer Portal.
- A Discord server where you can invite a bot.
- Your Discord user ID.

## Install nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## Enable the Discord channel

Install the optional channel dependency:

```bash
nanobot plugins enable discord
```

Create a Discord application, add a bot, copy the token, and enable
`MESSAGE CONTENT INTENT` in the bot settings.

Merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "allowChannels": [],
      "groupPolicy": "mention",
      "streaming": true
    }
  }
}
```

Invite the bot with permissions to read history and send messages.

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## Test a message

Send the bot a DM from your allowed account, or mention it in an allowed server
channel:

```text
@your-bot Hello from Discord
```

## Security notes

- Keep `groupPolicy` as `mention` for first deployment.
- Use `allowChannels` for server channels where the bot should operate.
- Avoid open group behavior in busy channels until session routing is clear.
- Review tool access before inviting the bot into shared servers.

## Troubleshooting

- If no messages arrive, confirm Message Content intent is enabled.
- If server messages are ignored, check `allowFrom`, `allowChannels`, and
  whether the bot was mentioned.
- If the bot cannot reply, confirm the invite permissions and channel overrides.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [AI Agent Memory](./ai-agent-memory.md)
- [Configure MCP tools](./configure-mcp-tools.md)
