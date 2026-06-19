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
| Ports are planned | Gateway health defaults to `18790`; WebUI/WebSocket defaults to `8765`; `nanobot serve` defaults to `8900` |
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
> The gateway and WebSocket channel default to `host: "127.0.0.1"` in `config.json` (set in `nanobot/config/schema.py`). Docker `-p` port forwarding cannot reach a container's loopback interface, so for the host or LAN to reach the exposed ports you must set both binds to `0.0.0.0` in `~/.nanobot/config.json` before starting the container. To serve the bundled WebUI from Docker, enable the WebSocket channel and protect bootstrap with a secret:
>
> ```json
> {
>   "gateway": { "host": "0.0.0.0" },
>   "channels": {
>     "websocket": {
>       "enabled": true,
>       "host": "0.0.0.0",
>       "port": 8765,
>       "tokenIssueSecret": "your-secret-here"
>     }
>   }
> }
> ```
>
> When the WebSocket `host` is `0.0.0.0`, the channel refuses to start unless `token` or `tokenIssueSecret` is also configured. See [`webui.md#lan-access`](./webui.md#lan-access) for details.

### Docker Compose

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

### Docker

```bash
# Build the image
docker build -t nanobot .

# Initialize config (first time only)
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot onboard

# Edit config on host to add API keys
vim ~/.nanobot/config.json

# Run gateway (connects to enabled channels, e.g. Telegram/Discord/Mochat).
# Mirrors the security caps and port mappings declared in docker-compose.yml:
#   - `--cap-drop ALL --cap-add SYS_ADMIN` + unconfined apparmor/seccomp are required
#     when `tools.exec.sandbox: "bwrap"` is enabled (bwrap needs CAP_SYS_ADMIN for
#     user namespaces). Without them, `bwrap` exits with `clone3: Operation not permitted`.
#   - `-p 8765:8765` exposes the WebSocket channel / WebUI alongside the gateway health
#     endpoint on 18790.
docker run \
  --cap-drop ALL --cap-add SYS_ADMIN \
  --security-opt apparmor=unconfined \
  --security-opt seccomp=unconfined \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  -p 18790:18790 -p 8765:8765 \
  nanobot gateway

# Or run a single command
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot status
```

## Linux Service

Run the gateway as a systemd user service so it starts automatically and restarts on failure.

**1. Find the nanobot binary path:**

```bash
which nanobot   # e.g. /home/user/.local/bin/nanobot
```

**2. Create the service file** at `~/.config/systemd/user/nanobot-gateway.service` (replace `ExecStart` path if needed):

```ini
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

**3. Enable and start:**

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-gateway
```

**Common operations:**

```bash
systemctl --user status nanobot-gateway        # check status
systemctl --user restart nanobot-gateway       # restart after config changes
journalctl --user -u nanobot-gateway -f        # follow logs
```

If you edit the `.service` file itself, run `systemctl --user daemon-reload` before restarting.

> **Note:** User services only run while you are logged in. To keep the gateway running after logout, enable lingering:
>
> ```bash
> loginctl enable-linger $USER
> ```

## macOS LaunchAgent

Use a LaunchAgent when you want `nanobot gateway` to stay online after you log in, without keeping a terminal open.

**1. Get the absolute `nanobot` path:**

```bash
which nanobot   # e.g. /Users/youruser/.local/bin/nanobot
```

Use that exact path in the plist. It keeps the Python environment from your install method.

**2. Create `~/Library/LaunchAgents/ai.nanobot.gateway.plist`:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>ai.nanobot.gateway</string>

  <key>ProgramArguments</key>
  <array>
    <string>/Users/youruser/.local/bin/nanobot</string>
    <string>gateway</string>
    <string>--workspace</string>
    <string>/Users/youruser/.nanobot/workspace</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/youruser/.nanobot/workspace</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>

  <key>StandardOutPath</key>
  <string>/Users/youruser/.nanobot/logs/gateway.log</string>

  <key>StandardErrorPath</key>
  <string>/Users/youruser/.nanobot/logs/gateway.error.log</string>
</dict>
</plist>
```

**3. Load and start it:**

```bash
mkdir -p ~/Library/LaunchAgents ~/.nanobot/logs
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.nanobot.gateway.plist
launchctl enable gui/$(id -u)/ai.nanobot.gateway
launchctl kickstart -k gui/$(id -u)/ai.nanobot.gateway
```

**Common operations:**

```bash
launchctl list | grep ai.nanobot.gateway
launchctl kickstart -k gui/$(id -u)/ai.nanobot.gateway   # restart
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.nanobot.gateway.plist
```

After editing the plist, run `launchctl bootout ...` and `launchctl bootstrap ...` again.

> **Note:** if startup fails with "address already in use", stop the manually started `nanobot gateway` process first.
