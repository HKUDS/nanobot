# Build a WhatsApp AI Agent with nanobot

This guide connects nanobot to WhatsApp through the `whatsapp` channel. The channel links as a WhatsApp device and uses the same nanobot agent runtime, tools, memory, and workspace as the CLI and WebUI.

> [!NOTE]
> WhatsApp also offers an official Agent Platform where the agent appears as its own chat and talks only to you. That is a separate channel with different tradeoffs — no group support, no end-to-end encryption, and limited country availability, but an officially supported interface that does not rely on a linked device. See [Connect nanobot to WhatsApp Agent Platform](./whatsapp-agent-platform.md) to compare them.

## What this guide builds

- WhatsApp optional dependencies installed
- a linked WhatsApp device session
- the `whatsapp` channel enabled in `config.json`
- one pairing-approved WhatsApp sender

## Prerequisites

- A normal reply in your existing nanobot WebUI or CLI. If you have not reached that point, complete [Quick Start](../quick-start.md) first.

- A WhatsApp account that can link a new device.
- A machine that can keep `nanobot gateway` running.

## Continue from your running instance

If you are already chatting in the WebUI, keep it open and continue below. It has already started the gateway. To reopen it later, use the same installation's `nanobot webui` command; there is no need to install nanobot again.

For terminal or server setup, use the manual configuration section below. Reuse the config/home and executable from your working instance. Docker users should use the [container commands](../deployment.md#docker-compose).

## Enable the WhatsApp channel

Open **Channels → WhatsApp**, install support if prompted, and follow the QR connection flow. Scan the code from **WhatsApp → Settings → Linked Devices**. Enable the channel and save; choose mention-only group replies under **Advanced** for a first deployment. Follow any restart prompt.

<details>
<summary>Manual configuration</summary>

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

Omitting `allowFrom` enables pairing-only mode for private chats. `groupPolicy` defaults to `"open"` in the channel, but `"mention"` is safer for a first deployment.

</details>

## Apply the settings

In the WebUI, follow any restart prompt and keep the launcher running for the first test. You do not need to start another gateway. For unattended operation afterward, use [background or service mode](../cli-reference.md#gateway).

For manual config changes, restart the existing gateway through its owning terminal, `nanobot gateway restart` for background mode, or its service/container supervisor. If none is running, start `nanobot gateway` and leave it running. Run diagnostic CLI commands in a separate terminal using the same installation and config.

## Test a message

Send the bot a private WhatsApp message. It should return a pairing code. Return to the WebUI pairing prompt and enter the code from your own private chat. Only a matching pending code is approved; do not enter another person's code. Then send your message again.

<details>
<summary>Terminal-only pairing</summary>

In a separate local terminal, using the same instance:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Replace the example code with your actual code.

</details>

Send the message again after approval. Confirm that your private chat now receives a normal agent reply.

## Security notes

- Treat the WhatsApp session database as account access.
- Prefer pairing-only mode for first setup. Add `allowFrom` only when you want a static allowlist.
- Keep `groupPolicy` as `"mention"` before adding the bot to groups.
- Avoid `allowFrom: ["*"]` unless the bot is intentionally public or isolated.

## Troubleshooting

- If QR linking fails, rerun `nanobot channels login whatsapp`.
- If you are migrating from the old bridge, remove `bridgeUrl` and `bridgeToken`, then re-login.
- If a sender appears as a LID instead of a phone number, let nanobot learn the mapping at runtime or use `lidMappings` in the full reference.
- If a first private message returns a pairing code, approve it before testing normal replies.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [Secure local AI agent](./secure-local-ai-agent.md)
- [Deployment](../deployment.md)
