# Connect Telegram Bots to nanobot

This guide uses the WebUI to connect one or more Telegram bots. Each bot can be
named, checked, and turned on or off separately, so you can use different bots
for personal chats, a team, or a public-facing workflow.

## Before you start

Make sure nanobot can answer from the command line:

```bash
nanobot agent -m "Hello!"
```

You also need:

- a Telegram account
- a bot token from `@BotFather` for each bot you want to connect

Never share a bot token. Anyone who has it can control that Telegram bot.

## 1. Create a Telegram bot

1. Open Telegram and start a chat with `@BotFather`.
2. Send `/newbot` and follow the prompts.
3. Copy the token BotFather gives you.

Repeat these steps if you want more than one bot. Each nanobot entry must use a
different BotFather token.

## 2. Open Telegram settings in nanobot

Install Telegram support in the same environment where nanobot is installed:

```bash
nanobot plugins enable telegram
```

Then start the WebUI:

```bash
nanobot webui
```

Open **Settings → Channels → Telegram**. If the page asks you to install or
restart Telegram support, follow the prompt and return to the Telegram card.

## 3. Connect your first bot

1. Enter a short **Bot name**, such as `Personal` or `Support`. This is only a
   label inside nanobot; it does not rename the bot in Telegram.
2. Paste the BotFather token.
3. Select **Check and connect**.

nanobot asks Telegram to verify the token before saving it. A rejected token is
not saved. After a successful check, the token is stored masked and the bot is
enabled.

## 4. Send a test message and pair your account

Open the bot in Telegram and send a direct message such as:

```text
Hello from Telegram
```

When `allowFrom` is empty, a new sender receives a pairing code. Approve it in
the WebUI, or from an already trusted surface:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Send the Telegram message again after approval. The bot should now reply using
your normal nanobot model, tools, memory, and workspace.

## Add and manage more bots

In **Settings → Channels → Telegram**, select **Add bot** and repeat the same
name, token, and connection check. Use a separate token for every entry.

Each bot has its own switch. Turning one bot off does not remove its settings or
stop the other bots. Use **Check connection** on any saved bot to confirm which
Telegram account its token belongs to.

Useful ways to separate bots include:

- a private bot and a team bot
- support and product-feedback bots
- bots for different communities or workflows

## Understand the connection messages

| Message | What it means | What to do |
|---|---|---|
| **Connected as @name** | Telegram accepted the saved token. | Send a test message. |
| **Telegram rejected this bot token** | The token is wrong, revoked, or belongs to a deleted bot. | Copy the current token from BotFather, or create a new one. |
| **Could not verify this token right now** | nanobot could not reach Telegram during first setup. | Check internet/proxy access and try again; the new token was not saved. |
| **A saved token was found, but Telegram could not verify it right now** | Settings already exist, but the live check could not reach Telegram. | Keep the gateway running and retry **Check connection** later. |

## Existing Telegram setups

An existing single-bot Telegram setup appears automatically as **Default bot**.
You do not need to paste its token again. You can check it, toggle it, and add
more bots from the same screen.

Before returning to an older nanobot release, back up
`~/.nanobot/config.json`. Once this version saves or switches a Telegram
bot—even if you only use one—older releases may no longer recognize the
Telegram settings.

## Polling and webhook deployments

Long polling is the default and is the easiest choice for local and private
deployments. It does not require a public URL.

Webhook mode is intended for deployments with a public HTTPS endpoint. If you
run several Telegram bots in webhook mode, give every enabled bot a different
local listening port—for example, `8081`, `8082`, and `8083`. Two bots cannot
listen on the same local address and port.

See the [Chat Apps reference](../chat-apps.md) for manual configuration and the
full webhook example.

## Troubleshooting

- **Telegram is missing from Channels:** run `nanobot plugins enable telegram`
  again in the Python environment that runs the gateway.
- **A token is rejected:** open BotFather, select the correct bot, and copy or
  regenerate its token. Do not reuse one token for two entries.
- **The live check is temporarily unavailable:** confirm the machine can reach
  `api.telegram.org` and that any configured proxy works, then retry.
- **A bot is connected but receives nothing:** confirm its switch is on and the
  nanobot gateway is still running.
- **The first DM returns a pairing code:** this is expected. Approve the code,
  then send the message again.
- **Telegram Web shows unsupported rich messages:** keep `richMessages`
  disabled.

## Security tips

- Start with pairing instead of allowing everyone.
- Do not use `allowFrom: ["*"]` unless the bot is intentionally public.
- Rotate a token immediately if it appears in logs, screenshots, or shared
  files.
- Review tool access before inviting a bot into group chats or adding more
  users.

## Next steps

- [Chat Apps reference](../chat-apps.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Configure MCP tools](./configure-mcp-tools.md)
