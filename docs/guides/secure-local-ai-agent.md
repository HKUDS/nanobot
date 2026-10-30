# How to Secure a Local AI Agent with nanobot

This guide covers the practical controls to review before letting a nanobot agent access files, shell commands, web fetch, chat apps, or remote users.

## What you will build

- a workspace-scoped agent setup
- narrow channel access
- safer secrets handling
- optional shell sandboxing on Linux

## When to use this

Use this before exposing nanobot to teammates, chat apps, public networks, broad web access, or unattended automations.

## Before you start

If nanobot is already open, continue in that WebUI. Otherwise follow the [first-run guide](../start-without-technical-background.md) to install it, configure a model, and send a test message.

## Minimal working example

Open **Settings → Advanced**. Enable workspace restriction, then choose the shell sandbox supported by your host (`bwrap` on Linux or `seatbelt` on macOS). Disable shell execution when the agent does not need it. Follow any restart prompt.

<details>
<summary>Manual configuration</summary>

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

`bwrap` is Linux-only and requires bubblewrap. On macOS, use `"sandbox": "seatbelt"`. Windows has no supported OS shell sandbox; disable shell execution if the application-level workspace guard is insufficient.

</details>

## Production notes

- Use environment variables for provider keys, bot tokens, and mailbox passwords.
- Use [separate instances and workspaces](../multiple-instances.md) for data that must not share memory. Project selection inside one instance does not isolate memory. Use separate OS accounts or containers for mutually untrusted users.
- Prefer [pairing](../configuration.md#pairing) for DM-capable chat apps. Slack and Mattermost DMs default to open access: set `dm.policy` to `"allowlist"` to require approval. Configure group access separately; mention-only controls when the bot responds, not who is trusted.
- Bind WebUI, WebSocket, and API services to localhost unless remote access is intentional. Share [WebUI access](../webui.md#sharing-access) only with trusted administrators; it has no per-user roles or private topic ownership.

## Security notes

- `restrictToWorkspace` is an application-level guard, not an OS sandbox.
- `tools.exec.enable: false` removes shell execution entirely.
- HTTP web fetch and HTTP MCP use SSRF protections by default. Shell commands and stdio MCP processes are outside this guard. Neither shell sandbox blocks network access; use host or container egress controls for an offline deployment.
- Adding broad `tools.ssrfWhitelist` ranges increases exposure.
- On channels using the common sender allowlist, `allowFrom: ["*"]` bypasses pairing and allows every sender. Slack and Mattermost use the DM and group policies described above.

## Troubleshooting

- If a needed file cannot be read, confirm the active workspace path.
- If a shell command fails under `bwrap`, check whether the command needs files outside the sandbox.
- If local HTTP tools are blocked, review the SSRF whitelist and use a narrow CIDR.

## Related nanobot docs

- [Configuration: Security](../configuration.md#security)
- [Pairing](../configuration.md#pairing)
- [Deployment](../deployment.md)
- [Chat Apps](../chat-apps.md)
