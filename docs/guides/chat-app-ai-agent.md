# How to Connect an AI Agent to Chat Apps with nanobot

nanobot can run as a self-hosted chatbot or AI agent in Telegram, Discord,
Slack, WeChat, Email, Mattermost, and other chat apps. The gateway receives chat
messages, runs the agent, and sends replies back to the same channel.

## What you will build

- a working local agent
- one enabled chat channel
- a running gateway
- a pairing-based approval flow or a narrow static allowlist

## When to use this

Use chat apps when the agent should live where users already communicate:
private DMs, team channels, group chats, email threads, or bot workspaces.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

Then choose one platform guide:

- [Telegram AI agent](./telegram-ai-agent.md)
- [Discord AI agent](./discord-ai-agent.md)
- [Slack AI agent](./slack-ai-agent.md)
- [Feishu AI agent](./feishu-ai-agent.md)
- [WhatsApp AI agent](./whatsapp-ai-agent.md)
- [WeChat AI agent](./wechat-ai-agent.md)
- [QQ AI agent](./qq-ai-agent.md)
- [Email AI agent](./email-ai-agent.md)
- [Mattermost AI agent](./mattermost-ai-agent.md)

## Minimal working example

Every channel follows the same pattern:

1. Get the platform token, login state, webhook, or mailbox credentials.
2. Merge the channel snippet into `~/.nanobot/config.json`.
3. Prefer pairing for DM-capable channels: omit `allowFrom`, then approve the
   first DM's pairing code.
4. For channels without pairing, such as Email, keep access narrow with
   `allowFrom` or platform-specific allow lists.
5. Check status:

```bash
nanobot channels status
```

6. Start the gateway:

```bash
nanobot gateway
```

7. Send a test DM, approve the pairing code when prompted, then send the test
   message again.

## Production notes

- Keep the gateway running as a service for always-on chat apps.
- Use mention-only group policies before opening a bot to busy channels.
- Use one channel at a time while debugging.
- Prefer DMs for first tests; pairing only works in DMs, and group chats add
  permissions and routing behavior.

## Security notes

- Prefer pairing or explicit allowlists; do not use `allowFrom: ["*"]` outside
  an intentional sandbox.
- Rotate bot tokens if they are pasted into logs or shared files.
- Review file, shell, and web tool access before inviting other users.

## Troubleshooting

- If `nanobot channels status` does not show the channel, the config key or
  optional dependency is likely missing.
- If the first DM returns a pairing code, approve it with
  `/pairing approve <code>` before expecting normal replies.
- If messages do not arrive, run `nanobot gateway --verbose` and compare
  platform credentials, event permissions, and allow lists.
- If group replies are unexpected, review that channel's group policy.

## Related nanobot docs

- [Chat Apps](../chat-apps.md)
- [Configuration](../configuration.md#channel-settings)
- [Pairing](../configuration.md#pairing)
- [Deployment](../deployment.md)
