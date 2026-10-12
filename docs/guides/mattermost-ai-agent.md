# Build a Mattermost AI Agent with nanobot

This guide connects nanobot to Mattermost through the built-in Mattermost channel, using WebSocket events and the Mattermost REST API.

## What this guide builds

- a Mattermost bot account or token
- the `mattermost` channel enabled in nanobot
- mention-only group behavior for first deployment
- one pairing-approved DM or mention test

## Prerequisites

- A normal reply in your existing nanobot WebUI or CLI. If you have not reached that point, complete [Quick Start](../quick-start.md) first.

- A Mattermost server URL.
- A bot token or personal access token for the bot account.

## Continue from your running instance

If you are already chatting in the WebUI, keep it open and continue below. It has already started the gateway. To reopen it later, use the same installation's `nanobot webui` command; there is no need to install nanobot again.

For terminal or server setup, use the manual configuration section below. Reuse the config/home and executable from your working instance. Docker users should use the [container commands](../deployment.md#docker-compose).

## Enable the Mattermost channel

Prepare the Mattermost bot token and team ID. In **Channels → Mattermost**, enter the server URL, token, and team ID. Use **Advanced** for group and thread policies; for DM pairing, choose **Allowlist** with an empty DM allowlist. Enable the channel, save, and follow any restart prompt.

DM approval does not restrict group access. With the mention policy below, any member can invoke the bot in a channel it can see. For DM-only access, set the group policy to **Allowlist** and leave the group allowlist empty. To allow selected channels, add their IDs; all members of those channels can then use the bot under the configured mention/thread rules.

<details>
<summary>Manual configuration</summary>

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
      "groupPolicyInThread": "open",
      "replyInThread": true,
      "dm": {
        "policy": "allowlist"
      }
    }
  }
}
```

`teamId` scopes the channel to a Mattermost team. Keep `groupPolicy` as `mention` for the first test. `groupPolicyInThread` can be `"mention"`, `"open"`, or `"allowlist"` and controls messages that reply inside a thread. If it is omitted, it inherits `groupPolicy`, preserving the behavior of existing configurations. Set it to `"open"` explicitly when follow-up messages in threads should not require another @mention.

When `groupPolicy` is `"allowlist"`, `groupAllowFrom` remains the outer channel boundary for root posts and thread replies. A thread policy cannot open a channel that is not on that allowlist.

Mattermost DMs are open by default. Setting `dm.policy` to `"allowlist"` with no `dm.allowFrom` entries makes new DM senders receive a pairing code. Approve the code before using the bot normally.

</details>

## Apply the settings

In the WebUI, follow any restart prompt and keep the launcher running for the first test. You do not need to start another gateway. For unattended operation afterward, use [background or service mode](../cli-reference.md#gateway).

For manual config changes, restart the existing gateway through its owning terminal, `nanobot gateway restart` for background mode, or its service/container supervisor. If none is running, start `nanobot gateway` and leave it running. Run diagnostic CLI commands in a separate terminal using the same installation and config.

## Test a message

DM the bot account. It should return a pairing code. Return to the WebUI pairing prompt and enter the code from your own private chat. Only a matching pending code is approved; do not enter another person's code. Then send your message again.

<details>
<summary>Terminal-only pairing</summary>

In a separate local terminal, using the same instance:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Replace the example code with your actual code.

</details>

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

- If startup logs say `serverUrl and token must be configured`, check the camelCase config keys.
- If DMs are ignored, review the `dm` policy and pairing approval state.
- If channel messages are ignored, confirm the bot is mentioned and belongs to the team/channel.
- If thread replies are surprising, review `groupPolicyInThread`, `replyInThread`, and `includeThreadContext`.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [Long-running AI Agent](./long-running-ai-agent.md)
- [Deployment](../deployment.md)
