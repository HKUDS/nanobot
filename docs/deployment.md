# Deployment

Use this page after `nanobot agent -m "Hello!"` works locally. Deployment keeps long-running surfaces online: WebUI, chat apps, heartbeat, Dream, cron jobs, and channel connections.

## Before You Deploy

Check these once before Docker, systemd, or LaunchAgent:

| Check | Why it matters |
|---|---|
| `nanobot status` shows the expected config and workspace | Confirms the process will read the instance you meant to run |
| `nanobot agent -m "Hello!"` works | Proves install, config, provider, model, and workspace writes before adding a service layer |
| Secrets are in environment variables or protected config files | API keys, bot tokens, OAuth state, and chat credentials should not be world-readable |
| `~/.nanobot/` or your custom config/workspace path is persistent | Sessions, memory, channel login state, generated artifacts, and cron jobs live there |
| Channel access control is intentional | Use `allowFrom`, pairing, WebSocket `token`/`tokenIssueSecret`, or private test channels before exposing the bot |
| Ports are planned | Gateway health defaults to local-only `127.0.0.1:18790`; WebUI/WebSocket defaults to `8765`; `nanobot serve` defaults to `8900` |
| Logs are easy to reach | Use `docker compose logs`, `journalctl`, LaunchAgent log files, or `nanobot gateway --verbose` while diagnosing startup |

Restart the deployed process after editing `config.json`. Long-running processes read config at startup.

## Choose a Runtime

| Runtime | Use it for | State location | Useful first command |
|---|---|---|---|
| Docker Compose | Repeatable container runs on Linux servers or workstations | Bind-mount `~/.nanobot` to `/home/nanobot/.nanobot` | `docker compose run --rm nanobot-cli agent -m "Hello!"` |
| Docker CLI | Manual container testing or small one-off hosts | Bind-mount `~/.nanobot` to `/home/nanobot/.nanobot` | `docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot status` |
| systemd user service | Linux user-level gateway that restarts automatically | Host user's `~/.nanobot` unless you pass explicit paths | `systemctl --user status nanobot-gateway` |
| macOS LaunchAgent | macOS gateway that starts after login | Host user's `~/.nanobot` unless the plist passes explicit paths | `launchctl list | grep ai.nanobot.gateway` |

## Docker

> [!TIP]
> The `-v ~/.nanobot:/home/nanobot/.nanobot` flag mounts your local config directory into the container, so your config and workspace persist across container restarts.
> The container runs as the non-root user `nanobot` (UID 1000) and reads config from `/home/nanobot/.nanobot`. Always mount your host config directory to `/home/nanobot/.nanobot`, not `/root/.nanobot`.
> If you get **Permission denied**, fix ownership on the host first: `sudo chown -R 1000:1000 ~/.nanobot`, or pass `--user $(id -u):$(id -g)` to match your host UID. Podman users can use `--userns=keep-id` instead.
>
> [!IMPORTANT]
> Official Docker usage currently means building from this repository with the included `Dockerfile`. Docker Hub images under third-party namespaces are not maintained or verified by HKUDS/nanobot; do not mount API keys or bot tokens into them unless you trust the publisher.

> [!IMPORTANT]
> The gateway and WebSocket channel default to `host: "127.0.0.1"` in `config.json` (set in `nanobot/config/schema.py`). Docker `-p` port forwarding cannot reach a container's loopback interface, so for the host or LAN to reach the exposed ports you must set both binds to `0.0.0.0` in `~/.nanobot/config.json` before starting the container. To serve the bundled WebUI from Docker, bind the WebSocket channel externally and protect bootstrap with a secret:
>
> ```json
> {
>   "gateway": { "host": "0.0.0.0" },
>   "channels": {
>     "websocket": {
>       "host": "0.0.0.0",
>       "port": 8765,
>       "tokenIssueSecret": "your-secret-here"
>     }
>   }
> }
> ```
>
> When the WebSocket `host` is `0.0.0.0`, the channel refuses to start unless `token` or `tokenIssueSecret` is also configured. See [`webui.md#lan-access`](./webui.md#lan-access) for details.
> The gateway health route itself is intentionally minimal and unauthenticated. When the
> container binds it to `0.0.0.0`, publish port `18790` to host loopback only; place any
> remotely monitored health endpoint behind a firewall or reverse proxy. If another host
> must probe it directly, replace `127.0.0.1` in the port mapping with a trusted host
> interface and restrict inbound traffic to the monitoring system.

### Docker Compose

The default image preinstalls WhatsApp dependencies. To bake other enabled
channels into an image (recommended for deployments without PyPI access), pass
a comma-separated `NANOBOT_CHANNELS` build argument:

```bash
NANOBOT_CHANNELS=telegram,slack docker compose build
```

The image keeps nanobot in a virtual environment owned by its built-in non-root
runtime user (UID 1000). If an enabled channel was not preinstalled, gateway
startup can therefore install its manifest-declared dependencies. Rebuilding
with `NANOBOT_CHANNELS` keeps that installation reproducible instead of relying
on the container's writable layer. If you override the container with a
different `--user`, bake every enabled channel into the image because that UID
is not guaranteed write access to the virtual environment.

```bash
docker compose run --rm nanobot-cli onboard   # first-time setup
vim ~/.nanobot/config.json                     # add API keys
docker compose up -d nanobot-gateway           # start gateway
```

```bash
docker compose run --rm nanobot-cli agent -m "Hello!"   # run CLI
docker compose logs -f nanobot-gateway                   # view logs
docker compose down                                      # stop
```

The default Compose file drops all Linux capabilities and keeps Docker's default
AppArmor/seccomp profiles enabled. If you explicitly set
`"tools.exec.sandbox": "bwrap"` in `~/.nanobot/config.json`, add the bwrap
override file when starting containers:

```bash
docker compose -f docker-compose.yml -f docker-compose.bwrap.yml up -d nanobot-gateway
docker compose -f docker-compose.yml -f docker-compose.bwrap.yml run --rm nanobot-cli agent -m "Hello!"
```

The override grants `CAP_SYS_ADMIN` and disables AppArmor/seccomp confinement for
the container so bubblewrap can create its nested namespaces. Use it only when the
bwrap sandbox is enabled.

### Docker

```bash
# Build the image
docker build -t nanobot .

# Or preinstall dependencies for a specific set of channels
docker build --build-arg NANOBOT_CHANNELS=telegram,slack -t nanobot .

# Initialize config (first time only)
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot onboard

# Edit config on host to add API keys
vim ~/.nanobot/config.json

# Run gateway (connects to enabled channels, e.g. Telegram/Discord/Mochat).
# `-p 8765:8765` exposes the WebSocket channel / WebUI alongside the gateway
# health endpoint on 18790.
docker run \
  --cap-drop ALL \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  -p 18790:18790 -p 8765:8765 \
  nanobot gateway

# If `tools.exec.sandbox: "bwrap"` is enabled, run with the extra permissions
# bubblewrap needs for nested namespaces. Without them, `bwrap` may exit with
# `clone3: Operation not permitted`.
docker run \
  --cap-drop ALL --cap-add SYS_ADMIN \
  --security-opt apparmor=unconfined \
  --security-opt seccomp=unconfined \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  -p 127.0.0.1:18790:18790 -p 8765:8765 \
  nanobot gateway

# Or run a single command
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot status
```

## Linux Service

Run the gateway as a systemd user service so it starts automatically and restarts on failure.

Preview the generated unit first:

```bash
nanobot gateway install-service --manager systemd --dry-run
```

Install, enable, and start it:

```bash
nanobot gateway install-service --manager systemd
```

For a custom instance, pass the same config/workspace selector you use to run the gateway:

```bash
nanobot gateway install-service \
  --manager systemd \
  --name nanobot-telegram \
  --config ~/.nanobot-telegram/config.json \
  --workspace ~/.nanobot-telegram/workspace
```

Common operations:

```bash
systemctl --user status nanobot-gateway        # check status
systemctl --user restart nanobot-gateway       # restart after config changes
journalctl --user -u nanobot-gateway -f        # follow logs
nanobot gateway uninstall-service --manager systemd
```

The installer writes `~/.config/systemd/user/nanobot-gateway.service`, runs
`systemctl --user daemon-reload`, enables the unit, and restarts it. It uses the
current Python executable with `python -m nanobot gateway --foreground`, so the
service runs in the same environment you used to install nanobot.

> **Note:** User services only run while you are logged in. To keep the gateway running after logout, enable lingering:
>
> ```bash
> loginctl enable-linger $USER
> ```

## macOS LaunchAgent

Use a LaunchAgent when you want `nanobot gateway` to stay online after you log in, without keeping a terminal open.

Preview the generated plist first:

```bash
nanobot gateway install-service --manager launchd --dry-run
```

Install, load, enable, and start it:

```bash
nanobot gateway install-service --manager launchd
```

For a custom instance:

```bash
nanobot gateway install-service \
  --manager launchd \
  --name nanobot-telegram \
  --config ~/.nanobot-telegram/config.json \
  --workspace ~/.nanobot-telegram/workspace
```

Common operations:

```bash
launchctl list | grep ai.nanobot.gateway
launchctl kickstart -k gui/$(id -u)/ai.nanobot.gateway
nanobot gateway uninstall-service --manager launchd
```

The installer writes `~/Library/LaunchAgents/ai.nanobot.gateway.plist`, uses the
current Python executable with `python -m nanobot gateway --foreground`, and
writes LaunchAgent logs under `~/.nanobot/logs/`.

> **Note:** if startup fails with "address already in use", stop the manually started `nanobot gateway` process first.
