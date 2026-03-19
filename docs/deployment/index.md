# Deployment Overview

This section explains how to deploy nanobot across different environments so you can pick the right strategy.

## Deployment options comparison

| Approach | Command | Use case | Persistence |
|----------|---------|----------|-------------|
| **CLI agent** | `nanobot agent` | One-off conversations, tests, scripts | None (runs once) |
| **Gateway service** | `nanobot gateway` | Long-running connection to chat platforms | Keep running manually or as a service |
| **Docker** | `docker compose up -d` | Containerized environments, CI/CD, isolated deployments | Persist via `restart: unless-stopped` |
| **systemd service** | `systemctl --user start nanobot-gateway` | Production Linux servers with auto-start | OS-level persistence with automatic restarts |

## Details per approach

### CLI agent (`nanobot agent`)

Ideal for quick tests or single dialogues. The process exits after you finish chatting.

```bash
nanobot agent -m "How’s the weather today?"
```

> **Note:** `nanobot agent` runs a local CLI agent and does not attach to any running `nanobot gateway` process.

### Gateway service (`nanobot gateway`)

The gateway is nanobot’s central service. It connects enabled chat channels (Telegram, Discord, Slack, etc.), listens for incoming messages, and loops the agent to respond.

See: [Gateway service guide](./gateway.md)

### Docker

Useful on machines where you cannot install Python directly or when you want isolated dependencies.

See: [Docker deployment guide](./docker.md)

### Linux systemd service

Best for reliable production deployments on Linux where you want auto-start and crash recovery.

See: [Linux service guide](./linux-service.md)

## Production vs. development

### Development recommendations

- Use `nanobot agent` for quick feature experiments
- Run `nanobot gateway` in the foreground to watch logs live
- Keep `"restrictToWorkspace": false` while debugging

```bash
nanobot gateway
```

### Production recommendations

- Deploy using Docker Compose or systemd to ensure uptime
- Set `"restrictToWorkspace": true` to limit workspace scope
- Centralize logs with `journalctl` or `docker compose logs`
- Configure auto-restart (`Restart=always` or `restart: unless-stopped`)

```bash
docker compose up -d nanobot-gateway
systemctl --user enable --now nanobot-gateway
```

## Config location

All deployment methods share the same config:

```
~/.nanobot/config.json          # main configuration
~/.nanobot/workspace/           # workspace directory
~/.nanobot/workspace/HEARTBEAT.md  # periodic tasks list
```

Run the onboarding wizard once to populate these files:

```bash
nanobot onboard
```

## Further reading

- [Gateway service guide](./gateway.md)
- [Docker deployment guide](./docker.md)
- [Linux service guide](./linux-service.md)
- [Architecture overview](../development/architecture.md)
