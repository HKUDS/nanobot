# Deployment

Use this page to keep nanobot running reliably in the background—on a hosted platform, in Docker, or as a Linux/macOS system service.

## Before You Deploy

Confirm these basics first (for a new container host, check them inside the container after setup):

- **Local setup works:** `nanobot status` shows the right config and workspace, and `nanobot agent -m "Hello!"` returns a reply.
- **Secrets are protected:** Keep API keys, bot tokens, and WebUI passwords in environment variables or private config files.
- **Data persists:** Keep your config directory (including `sessions/`) and workspace on persistent storage.
- **Access is locked down:** Configure pairing, `allowFrom`, or a WebUI password (`tokenIssueSecret`) before exposing nanobot beyond localhost.
- **Restart after edits:** Long-running services read `config.json` at startup—restart the service after config changes.

## Choose a Deployment Option

| Option | Best for | Where data lives |
|---|---|---|
| [Render](#render) | One-click hosted gateway + WebUI without managing a server | Render persistent disk (`/home/nanobot/.nanobot`) |
| [Docker Compose](#docker-compose) | Linux servers and repeatable container deployments | Bind mount `~/.nanobot` → `/home/nanobot/.nanobot` |
| [Linux Service](#linux-service) | Always-on gateway on a Linux machine (systemd) | Host `~/.nanobot` |
| [macOS LaunchAgent](#macos-launchagent) | Always-on gateway after login on a Mac | Host `~/.nanobot` |

## Render

Deploy the gateway and bundled WebUI together on Render with a persistent disk so your config, sessions, memory, and automations survive restarts.

> [!IMPORTANT]
> Requires a paid Render Starter plan because persistent disks are not available on the free tier. Have your `ANTHROPIC_API_KEY` ready, and generate a strong private password for `NANOBOT_WEB_TOKEN` (for example with `openssl rand -hex 32`).

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/HKUDS/nanobot) · [Review blueprint](../render.yaml)

1. Click **Deploy to Render**, sign in, and review the blueprint (one Starter web service + 1 GB persistent disk).
2. Enter your `ANTHROPIC_API_KEY` and set `NANOBOT_WEB_TOKEN` to a strong random password (save it in your password manager).
3. Create the blueprint and wait for the status to reach **Live** (the first build takes a few minutes).
4. Open your `onrender.com` URL and sign in with `NANOBOT_WEB_TOKEN`.

Automatic deploys are disabled by default so upstream changes do not unexpectedly restart your bot. To update later, open the Render Dashboard and click **Manual Deploy → Deploy latest commit**.

## Docker Compose

On a Linux host with Git and Docker Compose installed (no host Python required):

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
docker compose up -d
docker compose logs
```

On first boot, Compose creates `~/.nanobot/config.json` with container network settings and a random WebUI password printed in the logs. Open `http://<your-host>:8765`, enter that password, and configure your provider and model in **Settings → Models**.

- **Set your own password:** Export `NANOBOT_WEB_TOKEN="your-secret"` before running `docker compose up -d` for the first time.
- **Common commands:**

```bash
docker compose run --rm nanobot-cli agent -m "Hello!"   # test CLI
docker compose logs -f nanobot-gateway                   # follow logs
curl --fail http://127.0.0.1:18790/health                # health check
docker compose down                                      # stop
```

- **Preinstall chat channels into the image** (recommended when the container has slow or no PyPI access):

```bash
NANOBOT_CHANNELS=telegram,slack docker compose build
```

- **Remote access tip:** For a remote server, either restrict port `8765` with a firewall or connect over an SSH tunnel (`ssh -L 8765:127.0.0.1:8765 user@HOST`) and open `http://127.0.0.1:8765` locally.

<details>
<summary>Reusing an existing config, permissions, manual Docker CLI, and bwrap sandbox</summary>

- **Reusing an existing `config.json`:** Docker port forwarding cannot reach `127.0.0.1` inside a container. Set both `gateway.host` and `channels.websocket.host` to `"0.0.0.0"` and configure `channels.websocket.tokenIssueSecret` (see [LAN Access](./webui.md#lan-access)). Keep port `18790` (health check) bound to `127.0.0.1` on the host.
- **File permissions:** The container runs as UID `1000` (`nanobot`) and mounts `~/.nanobot` to `/home/nanobot/.nanobot`. If you see **Permission denied**, run `sudo chown -R 1000:1000 ~/.nanobot` on the host (or pass `--user $(id -u):$(id -g)` / Podman `--userns=keep-id`).
- **Official image note:** Build from this repository's `Dockerfile`; third-party images on Docker Hub are not maintained by HKUDS/nanobot.
- **Linux `bwrap` shell sandbox:** If you enable `"tools.exec.sandbox": "bwrap"`, start Compose with the bwrap override file so bubblewrap can create nested namespaces (requires host unprivileged user namespaces):

```bash
docker compose -f docker-compose.yml -f docker-compose.bwrap.yml up -d nanobot-gateway
```

- **Manual Docker CLI:**

```bash
docker build -t nanobot .
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot onboard
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot agent -m "Hello!"
docker run \
  --cap-drop ALL --cap-add CHOWN --cap-add SETGID --cap-add SETUID \
  --security-opt no-new-privileges:true \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  -p 127.0.0.1:18790:18790 -p 8765:8765 \
  nanobot gateway
```

</details>

<details>
<summary>Cloudflare Tunnel + Cloudflare Access</summary>

If you place a local `cloudflared` tunnel with Cloudflare Access in front of nanobot, you can let Cloudflare Access handle browser authentication instead of a WebUI password:

```json
{
  "gateway": { "host": "127.0.0.1" },
  "channels": {
    "websocket": {
      "host": "127.0.0.1",
      "port": 8765,
      "publicWsUrl": "wss://nanobot.example.com/",
      "trustedProxyAuth": {
        "trustedPeerCidrs": ["127.0.0.1/32", "::1/128"],
        "assertionHeader": "Cf-Access-Jwt-Assertion"
      }
    }
  }
}
```

nanobot requires both a direct loopback connection and a non-empty `Cf-Access-Jwt-Assertion` header (standard proxy headers like `X-Forwarded-*` are rejected). Because nanobot trusts the tunnel rather than cryptographically validating the JWT, never expose port `8765` directly to untrusted networks.

</details>

## Switch an Existing Gateway to a Service

Before installing a Linux or macOS service, stop any manually running gateway so the ports do not conflict:

- Close WebUI/TUI windows that might restart the gateway.
- Run `nanobot gateway stop` (or press `Ctrl+C` in a foreground terminal). Pass the same `--config` and `--workspace` if you use a custom instance.

## Linux Service

Run the gateway as a `systemd` user service so it starts automatically and restarts on failure:

```bash
nanobot gateway install-service --manager systemd --dry-run   # preview
nanobot gateway install-service --manager systemd             # install & start
```

For a custom instance, pass `--name`, `--config`, and `--workspace`:

```bash
nanobot gateway install-service \
  --manager systemd \
  --name nanobot-telegram \
  --config ~/.nanobot-telegram/config.json \
  --workspace ~/.nanobot-telegram/workspace
```

Common commands:

```bash
systemctl --user status nanobot-gateway
systemctl --user restart nanobot-gateway
journalctl --user -u nanobot-gateway -f
nanobot gateway uninstall-service --manager systemd
```

> [!TIP]
> To keep a user service running after you log out of Linux, enable lingering: `loginctl enable-linger $USER`.

## macOS LaunchAgent

Run the gateway automatically after you log in on macOS without keeping a terminal open:

```bash
nanobot gateway install-service --manager launchd --dry-run   # preview
nanobot gateway install-service --manager launchd             # install & start
```

Common commands:

```bash
launchctl list | grep ai.nanobot.gateway
launchctl kickstart -k gui/$(id -u)/ai.nanobot.gateway
nanobot gateway uninstall-service --manager launchd
```

Logs are written under `~/.nanobot/logs/`. If startup fails with "address already in use", stop any manually started gateway first.
