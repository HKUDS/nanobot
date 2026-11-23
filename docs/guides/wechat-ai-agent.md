# Build a WeChat AI Agent with nanobot

This guide connects nanobot to WeChat through the `weixin` channel. The channel uses HTTP long polling with QR-code login through the supported upstream API.

## What this guide builds

- the `weixin` channel enabled in nanobot
- a QR-code login session
- one pairing-approved WeChat sender
- a running gateway for message delivery

## Prerequisites

- A normal reply in your existing nanobot WebUI or CLI. If you have not reached that point, complete [Quick Start](../quick-start.md) first.

- A WeChat account that can complete QR-code login.

## Continue from your running instance

If you are already chatting in the WebUI, keep it open and continue below. It has already started the gateway. To reopen it later, use the same installation's `nanobot webui` command; there is no need to install nanobot again.

For terminal or server setup, use the manual configuration section below. Reuse the config/home and executable from your working instance. Docker users should use the [container commands](../deployment.md#docker-compose).

## Enable the WeChat channel

Open **Channels → WeChat (Weixin)**, install support if prompted, and follow the QR connection flow using your WeChat account. Enable the channel, save, and follow any restart prompt. New private senders receive a pairing code until approved.

<details>
<summary>Manual configuration</summary>

Install the optional channel dependency:

```bash
nanobot plugins enable weixin
```

Merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "weixin": {
      "enabled": true
    }
  }
}
```

Omitting `allowFrom` enables pairing-only mode. The first private WeChat message from a new sender gets a pairing code instead of agent access.

Log in:

```bash
nanobot channels login weixin
```

Use `--force` if you need to discard saved login state and authenticate again.

</details>

## Apply the settings

In the WebUI, follow any restart prompt and keep the launcher running for the first test. You do not need to start another gateway. For unattended operation afterward, use [background or service mode](../cli-reference.md#gateway).

For manual config changes, restart the existing gateway through its owning terminal, `nanobot gateway restart` for background mode, or its service/container supervisor. If none is running, start `nanobot gateway` and leave it running. Run diagnostic CLI commands in a separate terminal using the same installation and config.

## Test a message

Send a private WeChat message to the bot. It should reply with a pairing code. Return to the WebUI pairing prompt and enter the code from your own private chat. Only a matching pending code is approved; do not enter another person's code. Then send your message again.

<details>
<summary>Terminal-only pairing</summary>

In a separate local terminal, using the same instance:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Replace the example code with your actual code.

</details>

Send the message again after approval and watch gateway logs for the sender ID and reply.

## Security notes

- Prefer pairing-only mode for first setup. Add `allowFrom` only when you want a static allowlist.
- Treat saved login state as sensitive account access.
- Avoid connecting personal accounts to untrusted workspaces or broad tool permissions.

## Troubleshooting

- If login fails, rerun `nanobot channels login weixin --force`.
- If a first private message returns a pairing code, that is expected. Approve the code before testing normal agent replies.
- If messages are denied without a pairing code, check gateway logs for whether WeChat provided the context token required for nanobot to reply.
- If polling disconnects, restart the gateway and check network reachability to the upstream service.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [Secure local AI agent](./secure-local-ai-agent.md)
- [Deployment](../deployment.md)
