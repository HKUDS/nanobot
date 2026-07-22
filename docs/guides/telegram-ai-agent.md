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

## 2. Install support and open Telegram settings

Install Telegram support in the same Python environment where nanobot runs:

```bash
nanobot plugins enable telegram
```

Then start the WebUI:

```bash
nanobot webui
```

Open **Settings → Channels → Telegram**.

## 3. Connect your first bot

1. Paste the BotFather token. This is the only required field.
2. If needed, expand **Advanced options** to set a local bot name or an HTTP or
   SOCKS proxy, for example `http://127.0.0.1:7890`.
3. Select **Check and connect**.

nanobot asks Telegram to verify the token before saving it. A rejected token is
not saved. After a successful check, the token is stored masked and the bot is
enabled. When you enter a proxy, the same proxy is used for both this check and
the bot's normal Telegram traffic. Proxy credentials remain masked in the
WebUI after saving.

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
token check. Use a separate token for every entry; set a local name or proxy
under **Advanced options** only when needed.

Each bot has its own switch. Turning one bot off does not remove its settings or
stop the other bots. Use **Check connection** on any saved bot to confirm which
Telegram account its token belongs to.

To add or change a proxy for a saved bot, open the bot, expand **Advanced**,
enter the new URL under **Network proxy**, and select **Check and save**. The
saved URL is never shown again. Select **Remove saved proxy** when that bot can
connect directly. If an older setup shows a saved proxy before its token is
complete, you can remove the proxy from that same setup form before checking
the new token.

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
| **Telegram could not be reached through this proxy** | The proxy is offline, its address is wrong, or its credentials were rejected. | Check the proxy URL and credentials, then try **Check and save** again. |
| **Enter a full proxy URL** | The proxy address is missing a supported scheme or host. | Use a complete URL beginning with `http://`, `https://`, `socks5://`, or `socks5h://`. |
| **A saved token was found, but Telegram could not verify it right now** | Settings already exist, but the live check could not reach Telegram. | Keep the gateway running and retry **Check connection** later. |

## Existing Telegram setups

An existing single-bot Telegram setup appears automatically under its saved
name. You do not need to paste its token again. You can check it, toggle it,
and add more bots from the same screen.

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

- **Telegram support is not installed:** run `nanobot plugins enable telegram`
  in the Python environment that runs the gateway.
- **A token is rejected:** open BotFather, select the correct bot, and copy or
  regenerate its token. Do not reuse one token for two entries.
- **The live check is temporarily unavailable:** confirm the machine can reach
  `api.telegram.org`. If direct access is blocked, open **Network proxy** for
  that bot, enter the proxy URL, and select **Check and save**.
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
- Treat a proxy URL containing a username or password like any other secret.
- Review tool access before inviting a bot into group chats or adding more
  users.

## Next steps

- [Chat Apps reference](../chat-apps.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Configure MCP tools](./configure-mcp-tools.md)
