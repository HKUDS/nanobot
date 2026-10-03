# How to Secure a Local AI Agent with nanobot

This guide covers the practical controls to review before letting a nanobot
agent access files, shell commands, web fetch, chat apps, or remote users.

## What you will build

- a workspace-scoped agent setup
- narrow channel access
- safer secrets handling
- optional shell sandboxing on Linux

## When to use this

Use this before exposing nanobot to teammates, chat apps, public networks, broad
web access, or unattended automations.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

## Minimal working example

Start with workspace restriction:

```json
{
  "tools": {
    "restrictToWorkspace": true,
    "exec": {
      "enable": true,
      "sandbox": "bwrap"
    }
  }
}
```

`bwrap` is Linux-only and requires bubblewrap. On macOS or Windows, keep
`restrictToWorkspace` enabled and review shell access carefully.

## Production notes

- Use environment variables for provider keys, bot tokens, and mailbox
  passwords.
- Keep one workspace per trust boundary.
- Prefer pairing for DM-capable chat apps, use narrow `allowFrom` lists only
  when static allowlists are intentional, and keep group policy mention-only at
  first.
- Bind WebUI, WebSocket, and API services to localhost unless remote access is
  intentional.

## Security notes

- `restrictToWorkspace` is an application-level guard, not an OS sandbox.
- `tools.exec.enable: false` removes shell execution entirely.
- HTTP web fetch and HTTP MCP use SSRF protections by default.
- Adding broad `tools.ssrfWhitelist` ranges increases exposure.
- `allowFrom: ["*"]` bypasses pairing and means anyone who can reach that
  channel can talk to the bot.

## Troubleshooting

- If a needed file cannot be read, confirm the active workspace path.
- If a shell command fails under `bwrap`, check whether the command needs files
  outside the sandbox.
- If local HTTP tools are blocked, review the SSRF whitelist and use a narrow
  CIDR.

## Related nanobot docs

- [Configuration: Security](../configuration.md#security)
- [Pairing](../configuration.md#pairing)
- [Deployment](../deployment.md)
- [Chat Apps](../chat-apps.md)
