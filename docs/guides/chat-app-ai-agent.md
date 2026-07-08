# How to Connect an AI Agent to Chat Apps with nanobot

nanobot can run as a self-hosted chatbot or AI agent in Telegram, Discord,
Slack, WeChat, Email, Mattermost, and other chat apps. The gateway receives chat
messages, runs the agent, and sends replies back to the same channel.

## What you will build

- a working local agent
- one enabled chat channel
- a running gateway
- a narrow access-control rule for the first test user

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
- [WeChat AI agent](./wechat-ai-agent.md)
- [Email AI agent](./email-ai-agent.md)
- [Mattermost AI agent](./mattermost-ai-agent.md)

## Minimal working example

Every channel follows the same pattern:

1. Get the platform token, login state, webhook, or mailbox credentials.
2. Merge the channel snippet into `~/.nanobot/config.json`.
3. Keep access narrow with `allowFrom`, `allowChannels`, or pairing.
4. Check status:

```bash
nanobot channels status
```

5. Start the gateway:

```bash
nanobot gateway
```

6. Send a test message from an allowed account.

## Production notes

- Keep the gateway running as a service for always-on chat apps.
- Use mention-only group policies before opening a bot to busy channels.
- Use one channel at a time while debugging.
- Prefer DMs for first tests; group chats add permissions and routing behavior.

## Security notes

- Do not use `allowFrom: ["*"]` outside an intentional sandbox.
- Rotate bot tokens if they are pasted into logs or shared files.
- Review file, shell, and web tool access before inviting other users.

## Troubleshooting

- If `nanobot channels status` does not show the channel, the config key or
  optional dependency is likely missing.
- If messages do not arrive, run `nanobot gateway --verbose` and compare
  platform credentials, event permissions, and allow lists.
- If group replies are unexpected, review that channel's group policy.

## Related nanobot docs

- [Chat Apps](../chat-apps.md)
- [Configuration](../configuration.md#channel-settings)
- [Pairing](../configuration.md#pairing)
- [Deployment](../deployment.md)
