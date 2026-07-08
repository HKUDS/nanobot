# Build a Mattermost AI Agent with nanobot

This guide connects nanobot to Mattermost through the built-in Mattermost
channel, using WebSocket events and the Mattermost REST API.

## What this guide builds

- a Mattermost bot account or token
- the `mattermost` channel enabled in nanobot
- mention-only group behavior for first deployment
- one pairing-approved DM or mention test

## Prerequisites

- A working local nanobot reply:

```bash
nanobot agent -m "Hello!"
```

- A Mattermost server URL.
- A bot token or personal access token for the bot account.

## Install nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## Enable the Mattermost channel

Merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "mattermost": {
      "enabled": true,
      "serverUrl": "https://mattermost.example.com",
      "token": "YOUR_MATTERMOST_TOKEN",
      "teamId": "YOUR_TEAM_ID",
      "groupPolicy": "mention",
      "replyInThread": true,
      "dm": {
        "policy": "allowlist"
      }
    }
  }
}
```

`teamId` scopes the channel to a Mattermost team. Keep `groupPolicy` as
`mention` for the first test.

Mattermost DMs are open by default. Setting `dm.policy` to `"allowlist"` with no
`dm.allowFrom` entries makes new DM senders receive a pairing code. Approve the
code before using the bot normally.

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## Test a message

DM the bot account. It should return a pairing code. Approve it from a trusted
local surface:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Then DM the bot again, or mention it in a channel where the bot has access:

```text
@nanobot Hello from Mattermost
```

## Security notes

- Store the Mattermost token in an environment variable for deployed services.
- Keep `dm.policy` as `"allowlist"` when you want pairing-based approval.
- Use mention-only group behavior before opening the bot to busy channels.
- Review file and shell tools before inviting broad channel access.

## Troubleshooting

- If startup logs say `serverUrl and token must be configured`, check the
  camelCase config keys.
- If DMs are ignored, review the `dm` policy and pairing approval state.
- If channel messages are ignored, confirm the bot is mentioned and belongs to
  the team/channel.
- If thread replies are surprising, review `replyInThread` and
  `includeThreadContext`.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Deployment](../deployment.md)
