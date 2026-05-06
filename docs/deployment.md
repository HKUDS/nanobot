# Deployment

## Docker

> [!TIP]
> The `-v ~/.nanobot:/home/nanobot/.nanobot` flag mounts your local config directory into the container, so your config and workspace persist across container restarts.
> The container runs as the non-root user `nanobot` (UID 1000) and reads config from `/home/nanobot/.nanobot`. Always mount your host config directory to `/home/nanobot/.nanobot`, not `/root/.nanobot`.
> If you get **Permission denied**, fix ownership on the host first: `sudo chown -R 1000:1000 ~/.nanobot`, or pass `--user $(id -u):$(id -g)` to match your host UID. Podman users can use `--userns=keep-id` instead.
>
> [!IMPORTANT]
> Official Docker usage currently means building from this repository with the included `Dockerfile`. Docker Hub images under third-party namespaces are not maintained or verified by HKUDS/nanobot; do not mount API keys or bot tokens into them unless you trust the publisher.

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

# Run gateway (connects to enabled channels, e.g. Telegram/Discord/Mochat)
docker run -v ~/.nanobot:/home/nanobot/.nanobot -p 18790:18790 nanobot gateway

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

## Exposing nanobot publicly

nanobot is built for **one user, one machine, one long chat**. Publishing it through a public tunnel or reverse proxy works, but the trust boundary is not nanobot — it's whatever fronts it.

> [!CAUTION]
> Do **not** put the WebUI or `nanobot serve` behind a public tunnel without real authentication in front of `/`, `/webui/bootstrap`, `/api/*`, and the WebSocket upgrade path. nanobot does not authenticate human users for the embedded WebUI.

For public WebSocket use, expose **only** the WS path with:

- `webuiBootstrapDisabled: true` (or bind to a non-loopback host, which disables bootstrap automatically)
- `websocketRequiresToken: true`
- A strong `tokenIssueSecret`
- TLS in front (terminated by the proxy or via `sslCertfile` / `sslKeyfile`)
- A real auth boundary at the proxy (basic auth, OAuth, mTLS, IP allowlist)

For the OpenAI-compatible API (`nanobot serve`):

- Set a strong `api.authToken` (or pass `--auth-token`); requests to `/v1/*` will then require `Authorization: Bearer <token>`.
- The CLI **refuses to start** when `--host` is non-loopback and no auth token is configured.
- `/health` stays open so liveness probes don't need credentials.

### Why nanobot fails loud on unsafe configs

Heuristics (peer-IP, `X-Forwarded-For`) are easy to defeat with a custom proxy that strips or omits headers. nanobot therefore makes the unsafe combinations a hard error at startup rather than relying on heuristics:

- WebSocket channel: refuses to start when `host` is not loopback and either `tokenIssuePath` is set without `tokenIssueSecret`, or `websocketRequiresToken: false` with no static `token`.
- WebUI bootstrap: refuses to mint a token when the channel is bound to a non-loopback host, when `webuiBootstrapDisabled: true`, when the TCP peer isn't loopback, or when standard proxy-hop headers are present.
- `nanobot serve`: refuses to start when the bind is non-loopback and no `api.authToken` is set.
