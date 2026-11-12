# Build a Slack AI Agent with nanobot

This guide connects nanobot to Slack through Socket Mode. No public webhook URL is required for the first working setup.

## What this guide builds

- a Slack app with Socket Mode
- a bot token and app-level token
- the `slack` channel enabled in nanobot
- a DM pairing flow and mention test from an approved Slack user

## Prerequisites

- A normal reply in your existing nanobot WebUI or CLI. If you have not reached that point, complete [Quick Start](../quick-start.md) first.

- Permission to create a Slack app in a workspace.

## Continue from your running instance

If you are already chatting in the WebUI, keep it open and continue below. It has already started the gateway. To reopen it later, use the same installation's `nanobot webui` command; there is no need to install nanobot again.

For terminal or server setup, use the manual configuration section below. Reuse the config/home and executable from your working instance. Docker users should use the [container commands](../deployment.md#docker-compose).

## Enable the Slack channel

Create a Slack app with Socket Mode, a bot token, an app-level token with `connections:write`, and the required event subscriptions. In **Channels → Slack**, enter those tokens, enable the channel, and save. For pairing, expand **Advanced**, set the DM policy to **Allowlist**, and leave its allowlist empty; follow any restart prompt.

DM approval does not restrict group access. With the mention policy below, any member can invoke the bot in a channel it can see. For DM-only access, set the group policy to **Allowlist** and leave the group allowlist empty. To allow selected channels, add their IDs; all members of those channels can then use the bot under the configured mention/thread rules.

<details>
<summary>Manual configuration</summary>

Install the optional channel dependency:

```bash
nanobot plugins enable slack
```

In Slack, create an app, enable Socket Mode, create an app-level token with `connections:write`, add bot scopes, subscribe to bot events, and install the app to your workspace.

Merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "groupPolicy": "mention",
      "dm": {
        "policy": "allowlist"
      }
    }
  }
}
```

Slack DMs are open by default. Setting `dm.policy` to `"allowlist"` with no `dm.allowFrom` entries makes new DM senders receive a pairing code. Approve the code before using the bot normally.

</details>

## Apply the settings

In the WebUI, follow any restart prompt and keep the launcher running for the first test. You do not need to start another gateway. For unattended operation afterward, use [background or service mode](../cli-reference.md#gateway).

For manual config changes, restart the existing gateway through its owning terminal, `nanobot gateway restart` for background mode, or its service/container supervisor. If none is running, start `nanobot gateway` and leave it running. Run diagnostic CLI commands in a separate terminal using the same installation and config.

## Test a message

DM the Slack bot directly. It should return a pairing code. Return to the WebUI pairing prompt and enter the code from your own private chat. Only a matching pending code is approved; do not enter another person's code. Then send your message again.

<details>
<summary>Terminal-only pairing</summary>

In a separate local terminal, using the same instance:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Replace the example code with your actual code.

</details>

Then DM the bot again, or mention it in a channel:

```text
@nanobot Hello from Slack
```

## Security notes

- Keep `groupPolicy` as `mention` unless the bot is intentionally listening to every channel message.
- Keep `dm.policy` as `"allowlist"` when you want pairing-based approval.
- Use `groupAllowFrom` with allowlist mode for approved channels.
- Reinstall the Slack app after changing scopes.
- Keep bot and app tokens out of committed config files.

## Troubleshooting

- If Socket Mode fails, confirm the app-level token starts with `xapp-`.
- If the bot cannot send files, add `files:write`, reinstall the app, and restart nanobot.
- If a DM responds normally without pairing, check that `dm.policy` is `"allowlist"`.
- If channel messages are ignored, check event subscriptions and group policy.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Configure web search](./configure-web-search.md)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Deployment](../deployment.md)
