# Build a WeChat AI Agent with nanobot

This guide connects nanobot to WeChat through the `weixin` channel. The channel
uses HTTP long polling with QR-code login through the supported upstream API.

## What this guide builds

- the `weixin` channel enabled in nanobot
- a QR-code login session
- one allowed WeChat sender
- a running gateway for message delivery

## Prerequisites

- A working local nanobot reply:

```bash
nanobot agent -m "Hello!"
```

- A WeChat account that can complete QR-code login.
- The sender ID from logs for `allowFrom`, or a temporary private test setup.

## Install nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## Enable the WeChat channel

Install the optional channel dependency:

```bash
nanobot plugins enable weixin
```

Merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "weixin": {
      "enabled": true,
      "allowFrom": ["YOUR_WECHAT_USER_ID"]
    }
  }
}
```

Log in:

```bash
nanobot channels login weixin
```

Use `--force` if you need to discard saved login state and authenticate again.

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## Test a message

Send a private WeChat message from the allowed account and watch gateway logs for
the sender ID and reply.

## Security notes

- Keep `allowFrom` narrow after you identify the sender ID.
- Treat saved login state as sensitive account access.
- Avoid connecting personal accounts to untrusted workspaces or broad tool
  permissions.

## Troubleshooting

- If login fails, rerun `nanobot channels login weixin --force`.
- If messages arrive but are ignored, update `allowFrom` with the sender ID
  shown in logs.
- If polling disconnects, restart the gateway and check network reachability to
  the upstream service.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [Secure local AI agent](./secure-local-ai-agent.md)
- [Deployment](../deployment.md)
