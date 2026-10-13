# Build a Discord AI Agent with nanobot

This guide connects nanobot to Discord so a Discord user or server channel can talk to your self-hosted AI agent through the nanobot gateway.

## What this guide builds

- a Discord bot application
- Message Content intent enabled
- the `discord` channel enabled in nanobot
- one direct message or mention test

## Prerequisites

- A normal reply in your existing nanobot WebUI or CLI. If you have not reached that point, complete [Quick Start](../quick-start.md) first.

- Access to the Discord Developer Portal.
- A Discord server where you can invite a bot.

## Continue from your running instance

If you are already chatting in the WebUI, keep it open and continue below. It has already started the gateway. To reopen it later, use the same installation's `nanobot webui` command; there is no need to install nanobot again.

For terminal or server setup, use the manual configuration section below. Reuse the config/home and executable from your working instance. Docker users should use the [container commands](../deployment.md#docker-compose).

## Enable the Discord channel

Create a Discord application and bot, enable **Message Content Intent**, and invite it with permission to read history and send messages. In **Channels → Discord**, enter the bot token, enable the channel, and save. Use **Advanced** for allowed channels and reply behavior; follow any restart prompt.

<details>
<summary>Manual configuration</summary>

Install the optional channel dependency:

```bash
nanobot plugins enable discord
```

Create a Discord application, add a bot, copy the token, and enable `MESSAGE CONTENT INTENT` in the bot settings.

Merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowChannels": [],
      "groupPolicy": "mention",
      "streaming": true,
      "replyToMessage": false
    }
  }
}
```

Omitting `allowFrom` enables pairing-only mode. A new user should DM the bot first, get a pairing code, and be approved before using the bot in servers.

Invite the bot with permissions to read history and send messages.

Set `replyToMessage` to `true` to make responses use Discord's native reply UI. It defaults to `false`, preserving the existing behavior.

</details>

## Apply the settings

In the WebUI, follow any restart prompt and keep the launcher running for the first test. You do not need to start another gateway. For unattended operation afterward, use [background or service mode](../cli-reference.md#gateway).

For manual config changes, restart the existing gateway through its owning terminal, `nanobot gateway restart` for background mode, or its service/container supervisor. If none is running, start `nanobot gateway` and leave it running. Run diagnostic CLI commands in a separate terminal using the same installation and config.

## Test a message

Send the bot a DM first. It should return a pairing code. Return to the WebUI pairing prompt and enter the code from your own private chat. Only a matching pending code is approved; do not enter another person's code. Then send your message again.

<details>
<summary>Terminal-only pairing</summary>

In a separate local terminal, using the same instance:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Replace the example code with your actual code.

</details>

After approval, mention it in an allowed server channel:

```text
@your-bot Hello from Discord
```

## Security notes

- Keep `groupPolicy` as `mention` for first deployment.
- Use `allowChannels` for server channels where the bot should operate.
- Prefer pairing-only mode for user access; add `allowFrom` only when you want a static allowlist.
- Avoid open group behavior in busy channels until session routing is clear.
- Review tool access before inviting the bot into shared servers.

## Troubleshooting

- If no messages arrive, confirm Message Content intent is enabled.
- If a DM returns a pairing code, approve it before testing normal replies.
- If server messages are ignored, check pairing approval, `allowChannels`, and whether the bot was mentioned.
- If the bot cannot reply, confirm the invite permissions and channel overrides.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [AI Agent Memory](./ai-agent-memory.md)
- [Configure MCP tools](./configure-mcp-tools.md)
