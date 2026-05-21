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

## Windows Service

### Option A: NSSM (recommended)

[NSSM](https://nssm.cc/) wraps any executable as a Windows Service with automatic restart and log management.

**1. Install NSSM** (via [scoop](https://scoop.sh/) or direct download):

```powershell
scoop install nssm
# or download from https://nssm.cc/download
```

**2. Find the nanobot executable path:**

```powershell
Get-Command nanobot | Select-Object Source
# e.g. C:\Users\YourUser\AppData\Local\Programs\Python\Python312\Scripts\nanobot.exe
```

**3. Create the service:**

```powershell
nssm install NanobotGateway "C:\path\to\nanobot.exe" gateway
nssm set NanobotGateway AppDirectory "%APPDATA%\nanobot"
nssm set NanobotGateway DisplayName "Nanobot Gateway"
nssm set NanobotGateway Start SERVICE_AUTO_START
nssm set NanobotGateway AppStdout "%APPDATA%\nanobot\logs\gateway.log"
nssm set NanobotGateway AppStderr "%APPDATA%\nanobot\logs\gateway.error.log"
nssm set NanobotGateway AppRotateFiles 1
nssm set NanobotGateway AppRotateBytes 10485760
```

**4. Start the service:**

```powershell
nssm start NanobotGateway
```

**Common operations:**

```powershell
nssm status NanobotGateway         # check status
nssm restart NanobotGateway        # restart
nssm stop NanobotGateway           # stop
nssm edit NanobotGateway           # open GUI editor
nssm remove NanobotGateway         # remove service
```

### Option B: Task Scheduler

For simpler auto-start without service management:

```powershell
$action = New-ScheduledTaskAction -Execute "nanobot" -Argument "gateway"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "NanobotGateway" -Action $action -Trigger $trigger -Settings $settings -Description "Nanobot AI assistant gateway"
```

### Windows Firewall

If you need remote access to the gateway or API server:

```powershell
New-NetFirewallRule -DisplayName "Nanobot Gateway" -Direction Inbound -LocalPort 18790 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "Nanobot API" -Direction Inbound -LocalPort 8900 -Protocol TCP -Action Allow
```

### Docker on Windows

Nanobot runs in Docker via Docker Desktop (WSL2 backend). The Dockerfile is Linux-based; use the Linux instructions above. Windows native Docker containers (nanoserver) are not currently supported — the Linux image works seamlessly through Docker Desktop's WSL2 integration.

> **Note:** On Windows, nanobot stores config in `%APPDATA%\nanobot` by default. The Docker path still uses `~/.nanobot` inside the container.

```powershell
# The ~ path works in PowerShell via Docker Desktop
docker run -v "$HOME/.nanobot:/home/nanobot/.nanobot" -p 18790:18790 nanobot gateway
```

### Windows Tips

**Long paths (>260 characters):** Windows has a legacy 260-character path limit. If your workspace is nested deeply, you may hit errors. To fix this:
- Enable the Long Paths registry setting: `reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f`
- Or keep your workspace close to the drive root (e.g. `C:\nanobot\workspace`)

**Editing config files:** Do not use Windows Notepad to edit `config.json` — it may save with a BOM (byte-order mark) or CRLF line endings, which can cause JSON parsing errors. Use [VS Code](https://code.visualstudio.com/), [Notepad++](https://notepad-plus-plus.org/), or any editor that saves UTF-8 without BOM.

**Corporate proxy / MITM certificates:** If you're behind a corporate proxy that intercepts HTTPS traffic, you may need to set:
```powershell
$env:REQUESTS_CA_BUNDLE = "C:\path\to\your\corporate-ca-bundle.pem"
$env:SSL_CERT_FILE = "C:\path\to\your\corporate-ca-bundle.pem"
```
Export the proxy's CA certificate chain to a PEM file and point these environment variables at it. Add them to your PowerShell profile (`$PROFILE`) for persistence.
