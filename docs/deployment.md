# Deployment

Use this page to keep an already working agent online, or start with the [Docker setup](#docker-compose) on a new headless host. A normal WebUI reply is sufficient to confirm an existing model setup; a CLI check is useful for terminal and container deployments. Deployment keeps long-running surfaces online: WebUI, chat apps, heartbeat, Dream, cron jobs, and channel connections.

## Before You Deploy

Check these before making a deployment persistent. For a new container host, perform them inside the container after the initialization steps below:

| Check | Why it matters |
|---|---|
| `nanobot status` shows the expected config and workspace | Confirms the process will read the instance you meant to run |
| `nanobot agent -m "Hello!"` works | Proves install, config, provider, model, and workspace writes before adding a service layer |
| Secrets are in environment variables or protected config files | API keys, bot tokens, OAuth state, and chat credentials should not be world-readable |
| The active config directory (including `sessions/`) and workspace are persistent | Sessions follow `--config`; memory, generated artifacts, and the workspace identity marker follow the workspace |
| Channel access control is intentional | Use `allowFrom`, pairing, WebSocket `token`/`tokenIssueSecret`, or private test channels before exposing the bot |
| Ports are planned | Gateway health defaults to local-only `127.0.0.1:18790`; WebUI/WebSocket defaults to `8765`; `nanobot serve` defaults to `8900` |
| Logs are easy to reach | Use `docker compose logs`, `journalctl`, LaunchAgent log files, or `nanobot gateway --verbose` while diagnosing startup |

Restart the deployed process after editing `config.json`. Long-running processes read config at startup.

## Choose a Runtime

| Runtime | Use it for | State location | Useful first command |
|---|---|---|---|
| Render | One-click hosted gateway and WebUI | Persistent disk at `/home/nanobot/.nanobot` | [Deploy to Render](#render) |
| Docker Compose | Repeatable container runs on Linux servers or workstations | Bind-mount `~/.nanobot` to `/home/nanobot/.nanobot` | `docker compose run --rm nanobot-cli agent -m "Hello!"` |
| Docker CLI | Manual container testing or small one-off hosts | Bind-mount `~/.nanobot` to `/home/nanobot/.nanobot` | `docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot status` |
| systemd user service | Linux user-level gateway that restarts automatically | Host user's `~/.nanobot` unless you pass explicit paths | `systemctl --user status nanobot-gateway` |
| macOS LaunchAgent | macOS gateway that starts after login | Host user's `~/.nanobot` unless the plist passes explicit paths | `launchctl list | grep ai.nanobot.gateway` |

## Render

Run nanobot online without managing a server. The blueprint deploys the gateway and bundled WebUI together, with a persistent disk so sessions, memory, and chat history survive restarts.

> [!IMPORTANT]
> This setup requires a paid Render service because persistent disks are not available on the free tier. During setup, provide `ANTHROPIC_API_KEY` and set `NANOBOT_WEB_TOKEN` to a strong private password (for example, generate one with `openssl rand -hex 32`).

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/HKUDS/nanobot)

[Review the deployment blueprint](../render.yaml)

### First Deployment

1. Click **Deploy to Render**, sign in, and review the Blueprint. It creates one Starter web service and a 1 GB persistent disk.
2. Enter your `ANTHROPIC_API_KEY`. Set `NANOBOT_WEB_TOKEN` to a new random value and save it in your password manager; this is the password for the public WebUI.
3. Create the Blueprint and wait for the service status to become **Live**. The first build can take several minutes.
4. Open the generated `onrender.com` URL. The **Authentication required** page means the gateway is running: enter the same `NANOBOT_WEB_TOKEN` value to open the WebUI.

The model API key is used by nanobot to call Anthropic. The Web token only protects access to this deployment; do not share it in issues, screenshots, or chat.

### Updates and Data

The Blueprint disables automatic deploys so upstream repository changes do not unexpectedly restart your agent. To update, open the service in the Render Dashboard and choose **Manual Deploy → Deploy latest commit**.

The persistent disk keeps `config.json`, sessions, memory, WebUI history, cron state, media, and logs across restarts and updates. The deployment initializes `config.json` only when it does not already exist, so settings changed later in the WebUI are not replaced on every boot.

If deployment fails, open the service **Logs** page first. A missing model key fails provider requests after startup, while an incorrect Web token leaves you on the authentication page.

## Docker

> [!TIP]
> The `-v ~/.nanobot:/home/nanobot/.nanobot` flag mounts your local config directory into the container, so your config and workspace persist across container restarts. The container runs as the non-root user `nanobot` (UID 1000) and reads config from `/home/nanobot/.nanobot`. Always mount your host config directory to `/home/nanobot/.nanobot`, not `/root/.nanobot`. If you get **Permission denied**, fix ownership on the host first: `sudo chown -R 1000:1000 ~/.nanobot`, or pass `--user $(id -u):$(id -g)` to match your host UID. Podman users can use `--userns=keep-id` instead.
>
> [!IMPORTANT]
> Official Docker usage currently means building from this repository with the included `Dockerfile`. Docker Hub images under third-party namespaces are not maintained or verified by HKUDS/nanobot; do not mount API keys or bot tokens into them unless you trust the publisher.

> [!IMPORTANT]
> The gateway and WebSocket channel default to `host: "127.0.0.1"` in `config.json` (set in `nanobot/config/schema.py`). Docker `-p` port forwarding cannot reach a container's loopback interface, so for the host or LAN to reach the exposed ports you must set both binds to `0.0.0.0` in `~/.nanobot/config.json` before starting the container. To serve the bundled WebUI from Docker, bind the WebSocket channel externally and protect bootstrap with `tokenIssueSecret`:
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
> When the WebSocket `host` is `0.0.0.0`, the channel refuses to start unless `token`, `tokenIssueSecret`, or a fully configured `trustedProxyAuth` is also configured. See [`webui.md#lan-access`](./webui.md#lan-access) for details. The gateway health route itself is intentionally minimal and unauthenticated. When the container binds it to `0.0.0.0`, publish port `18790` to host loopback only; place any remotely monitored health endpoint behind a firewall or reverse proxy. If another host must probe it directly, replace `127.0.0.1` in the port mapping with a trusted host interface and restrict inbound traffic to the monitoring system.

### Cloudflare Tunnel + Cloudflare Access

For a local `cloudflared` process in front of nanobot, Cloudflare Access can authenticate the user before forwarding the request and add `Cf-Access-Jwt-Assertion`. Opt in to trusted-proxy no-token mode only when the direct TCP peer is the tunnel process and the assertion is non-empty:

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

This is two-part authorization: a trusted direct loopback peer **and** a non-empty Cloudflare Access assertion. A trusted CIDR alone is not a bypass. For this flow `/webui/bootstrap` returns connection metadata without a bootstrap token or REST API token; the proxy assertion authorizes the WebSocket handshake and REST requests directly.

Set `publicWsUrl` to the browser-facing `wss://` endpoint when the tunnel sends the origin host header (such as `127.0.0.1:8765`); otherwise the WebUI could attempt to open its WebSocket directly against the loopback address. The assertion header must be generated by Cloudflare Access after authentication; routing/client metadata headers such as `Host`, `Forwarded`, `X-Forwarded-*`, `X-Real-IP`, and `CF-Connecting-IP` are rejected as `assertionHeader` values. Nanobot trusts the assertion but does not cryptographically validate the JWT, so configure the tunnel and Access policy carefully and do not expose the nanobot listener directly to untrusted clients. Forwarded client headers do not establish proxy trust.

### Docker Compose

On a new Linux host, install Git and Docker with the Compose plugin, then get the repository. You do not need to install Python or nanobot on the host:

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
docker compose build
docker compose run --rm nanobot-cli onboard
```

The last command initializes `~/.nanobot/config.json` and the workspace in the bind mount. Skip it when reusing an existing configuration. Edit that file on the host and merge your provider settings from [provider setup](./providers.md); select the provider/model you can access, either through the documented model preset or direct `agents.defaults.provider` and `agents.defaults.model` settings. Keep `agents.defaults.workspace` as a container path, normally `~/.nanobot/workspace` (resolved inside the container), rather than a host home-directory path.

Also merge the Docker bind and authentication settings [above](#docker): `gateway.host` and `channels.websocket.host` must be `0.0.0.0`, and `tokenIssueSecret` must be a private random value. These snippets are partial configuration, not replacements for your provider settings. Config `${VAR}` references require those variables inside every CLI and gateway container; Compose does not forward arbitrary host variables automatically. Either add the necessary `environment` entries to the services or keep credentials in the protected config file.


The default image preinstalls WhatsApp dependencies. To bake other enabled channels into an image (recommended for deployments without PyPI access), pass a comma-separated `NANOBOT_CHANNELS` build argument:

```bash
NANOBOT_CHANNELS=telegram,slack docker compose build
```

The image keeps nanobot in a virtual environment owned by its built-in non-root runtime user (UID 1000). If an enabled channel was not preinstalled, gateway startup can therefore install its manifest-declared dependencies. Rebuilding with `NANOBOT_CHANNELS` keeps that installation reproducible instead of relying on the container's writable layer. If you override the container with a different `--user`, bake every enabled channel into the image because that UID is not guaranteed write access to the virtual environment.

The first `docker compose up` bootstraps `~/.nanobot/config.json` with container-appropriate binds and generated secrets: the WebUI password (`NANOBOT_WEB_TOKEN`) and the OpenAI-compatible API key (`NANOBOT_API_KEY`). Export either variable before `up` to pin your own; otherwise the entrypoint generates one and prints it to the container log. An existing `config.json` is left untouched. Add provider keys afterwards in the WebUI settings or with `onboard`:

```bash
docker compose up -d nanobot-gateway                      # first boot writes ~/.nanobot/config.json
docker compose logs nanobot-gateway                       # shows the generated WebUI password and API key
```

The `nanobot-api` service (OpenAI-compatible endpoint on `127.0.0.1:8900`) needs a configured provider before it can serve, so it is opt-in via the `api` profile:

```bash
docker compose --profile api up -d                        # also start the API once a provider is configured
```

For a fully pre-configured setup, keep using first-time onboarding:

```bash
docker compose run --rm nanobot-cli status
docker compose run --rm nanobot-cli agent -m "Hello!"
# Continue only after a normal reply.
docker compose up -d nanobot-gateway
curl --fail http://127.0.0.1:18790/health
```

```bash
docker compose run --rm nanobot-cli agent -m "Hello!"   # run CLI
docker compose logs -f nanobot-gateway                   # view logs
docker compose down                                      # stop
```

Open `http://HOST:8765` and enter the configured `tokenIssueSecret` when prompted. For a remote host, allow access only from the intended network or use an SSH tunnel (`ssh -L 8765:127.0.0.1:8765 user@HOST`) and open `http://127.0.0.1:8765` locally. The health check confirms the process is reachable; send a browser message to verify the model and WebUI together.

The default Compose file drops all Linux capabilities except `CHOWN`, `SETUID`, and `SETGID`, which the root entrypoint needs to fix bind-mount ownership and become UID 1000. It also enables `no-new-privileges`, so the non-root process cannot regain those bootstrap capabilities through setuid binaries or file capabilities. Docker's default AppArmor/seccomp profiles remain enabled. If you explicitly set `"tools.exec.sandbox": "bwrap"` in `~/.nanobot/config.json`, add the bwrap override file when starting containers:

```bash
docker compose -f docker-compose.yml -f docker-compose.bwrap.yml up -d nanobot-gateway
docker compose -f docker-compose.yml -f docker-compose.bwrap.yml run --rm nanobot-cli agent -m "Hello!"
```

The override adds `CAP_SYS_ADMIN` and disables AppArmor/seccomp confinement for the container so bubblewrap can create its nested namespaces. It preserves `no-new-privileges`. The host must also allow unprivileged user namespaces; the override cannot bypass a host-level namespace restriction. Use it only when the bwrap sandbox is enabled.

### Docker

```bash
# Build the image
docker build -t nanobot .

# Or preinstall a regular Python extra such as Bedrock support
docker build --build-arg NANOBOT_EXTRAS=bedrock -t nanobot .

# Or preinstall dependencies for a specific set of channels
docker build --build-arg NANOBOT_CHANNELS=telegram,slack -t nanobot .

# Initialize config (first time only)
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot onboard

# Merge model/provider and Docker bind/auth settings as described above.
vim ~/.nanobot/config.json

# Verify the configuration and model before running the persistent gateway.
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot status
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot agent -m "Hello!"

# Run gateway (connects to enabled channels, e.g. Telegram/Discord/Mochat).
# `-p 8765:8765` exposes the WebSocket channel / WebUI alongside the gateway
# health endpoint on 18790.
docker run \
  --cap-drop ALL \
  --cap-add CHOWN --cap-add SETGID --cap-add SETUID \
  --security-opt no-new-privileges:true \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  -p 127.0.0.1:18790:18790 -p 8765:8765 \
  nanobot gateway

# If `tools.exec.sandbox: "bwrap"` is enabled, run with the extra permissions
# bubblewrap needs for nested namespaces. Without them, `bwrap` may exit with
# `clone3: Operation not permitted`.
docker run \
  --cap-drop ALL \
  --cap-add CHOWN --cap-add SETGID --cap-add SETUID --cap-add SYS_ADMIN \
  --security-opt no-new-privileges:true \
  --security-opt apparmor=unconfined \
  --security-opt seccomp=unconfined \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  -p 127.0.0.1:18790:18790 -p 8765:8765 \
  nanobot gateway

# Or run a single command
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/home/nanobot/.nanobot --rm nanobot status
```

## Switch an Existing Gateway to a Service

Before installing an OS service, finish active work and close WebUI/TUI launchers that could start another gateway. Stop the existing instance: use `nanobot gateway stop` for a recorded background gateway (including one retained by `/detach`), or Ctrl+C in the terminal running a foreground gateway. Pass the same `--config` and `--workspace` selectors to stop, status, and service-install commands for a custom instance.

The service installer does not take over an existing standalone process. Starting both on the same ports makes the new service fail. If an OS service already owns the instance, manage it with its service manager instead of launching another process.

## Linux Service

Run the gateway as a systemd user service so it starts automatically and restarts on failure. Complete the [existing-gateway handoff](#switch-an-existing-gateway-to-a-service) first if an instance is already running.

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

The installer writes `~/.config/systemd/user/nanobot-gateway.service`, runs `systemctl --user daemon-reload`, enables the unit, and restarts it. It uses the current Python executable with `python -m nanobot gateway --foreground`, so the service runs in the same environment you used to install nanobot.

> **Note:** User services only run while you are logged in. To keep the gateway running after logout, enable lingering:
>
> ```bash
> loginctl enable-linger $USER
> ```

## macOS LaunchAgent

Use a LaunchAgent when you want `nanobot gateway` to stay online after you log in, without keeping a terminal open. Complete the [existing-gateway handoff](#switch-an-existing-gateway-to-a-service) first if an instance is already running.

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

The installer writes `~/Library/LaunchAgents/ai.nanobot.gateway.plist`, uses the current Python executable with `python -m nanobot gateway --foreground`, and writes LaunchAgent logs under `~/.nanobot/logs/`.

> **Note:** if startup fails with "address already in use", stop the manually started `nanobot gateway` process first.
