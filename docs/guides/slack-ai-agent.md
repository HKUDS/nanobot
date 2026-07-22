# Build a Slack AI Agent with nanobot

This guide connects nanobot to Slack through Socket Mode. No public webhook URL
is required for the first working setup.

## What this guide builds

- a Slack app with Socket Mode
- a bot token and app-level token
- the `slack` channel enabled in nanobot
- a DM pairing flow and mention test from an approved Slack user

## Prerequisites

- A working nanobot reply:

```bash
nanobot agent -m "Hello!"
```

- Permission to create a Slack app in a workspace.

## Install nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## Enable the Slack channel

Install the optional channel dependency:

```bash
nanobot plugins enable slack
```

In Slack, create an app, enable Socket Mode, create an app-level token with
`connections:write`, add bot scopes, subscribe to bot events, and install the
app to your workspace.

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

Slack DMs are open by default. Setting `dm.policy` to `"allowlist"` with no
`dm.allowFrom` entries makes new DM senders receive a pairing code. Approve the
code before using the bot normally.

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## Test a message

DM the Slack bot directly. It should return a pairing code. Approve it from a
trusted local surface:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Then DM the bot again, or mention it in a channel:

```text
@nanobot Hello from Slack
```

## Security notes

- Keep `groupPolicy` as `mention` unless the bot is intentionally listening to
  every channel message.
- Keep `dm.policy` as `"allowlist"` when you want pairing-based approval.
- Use `groupAllowFrom` with allowlist mode for approved channels.
- Reinstall the Slack app after changing scopes.
- Keep bot and app tokens out of committed config files.

## Troubleshooting

- If Socket Mode fails, confirm the app-level token starts with `xapp-`.
- If the bot cannot send files, add `files:write`, reinstall the app, and
  restart nanobot.
- If a DM responds normally without pairing, check that `dm.policy` is
  `"allowlist"`.
- If channel messages are ignored, check event subscriptions and group policy.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Configure web search](./configure-web-search.md)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Deployment](../deployment.md)
