# Build a WhatsApp AI Agent with nanobot

This guide connects nanobot to WhatsApp through the `whatsapp` channel. The
channel links as a WhatsApp device and uses the same nanobot agent runtime,
tools, memory, and workspace as the CLI and WebUI.

## What this guide builds

- WhatsApp optional dependencies installed
- a linked WhatsApp device session
- the `whatsapp` channel enabled in `config.json`
- one pairing-approved WhatsApp sender

## Prerequisites

- A working local nanobot reply:

```bash
nanobot agent -m "Hello!"
```

- A WhatsApp account that can link a new device.
- A machine that can keep `nanobot gateway` running.

## Install nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## Enable the WhatsApp channel

Install the optional channel dependency:

```bash
nanobot plugins enable whatsapp
```

Link WhatsApp as a device:

```bash
nanobot channels login whatsapp
```

Scan the QR code from WhatsApp -> Settings -> Linked Devices.

Merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "groupPolicy": "mention"
    }
  }
}
```

Omitting `allowFrom` enables pairing-only mode for private chats. `groupPolicy`
defaults to `"open"` in the channel, but `"mention"` is safer for a first
deployment.

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## Test a message

Send the bot a private WhatsApp message. It should return a pairing code.
Approve it from a trusted local surface:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Send the message again after approval. The reply should use the same model and
workspace as your local CLI check.

## Security notes

- Treat the WhatsApp session database as account access.
- Prefer pairing-only mode for first setup. Add `allowFrom` only when you want a
  static allowlist.
- Keep `groupPolicy` as `"mention"` before adding the bot to groups.
- Avoid `allowFrom: ["*"]` unless the bot is intentionally public or isolated.

## Troubleshooting

- If QR linking fails, rerun `nanobot channels login whatsapp`.
- If you are migrating from the old bridge, remove `bridgeUrl` and
  `bridgeToken`, then re-login.
- If a sender appears as a LID instead of a phone number, let nanobot learn the
  mapping at runtime or use `lidMappings` in the full reference.
- If a first private message returns a pairing code, approve it before testing
  normal replies.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [Secure local AI agent](./secure-local-ai-agent.md)
- [Deployment](../deployment.md)
