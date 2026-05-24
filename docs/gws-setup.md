# Google Workspace CLI (gws) Setup

## Overview

`gws` is installed on the RPI host and mounted read-only into the nanobot container.
OAuth credentials are stored on the host at `~/.config/gws/` and mounted read-write
so tokens persist across container restarts.

## Installation (already done — v0.22.5)

```bash
# Download aarch64 Linux binary from GitHub releases
curl -L -o /tmp/gws.tar.gz https://github.com/googleworkspace/cli/releases/download/v0.22.5/google-workspace-cli-aarch64-unknown-linux-gnu.tar.gz
mkdir -p /tmp/gws_extract && tar -xzf /tmp/gws.tar.gz -C /tmp/gws_extract
sudo mv /tmp/gws_extract/gws /usr/local/bin/gws
```

## docker-compose mounts

In `docker-compose.yml` under `x-common-config.volumes`:

```yaml
- /usr/local/bin/gws:/usr/local/bin/gws:ro   # binary, read-only
- ~/.config/gws:/home/nanobot/.config/gws     # OAuth tokens, read-write
```

## First-time Auth (TODO — not yet completed)

Run on the RPI host (not inside the container):

```bash
# Step 1: set up Google Cloud project and OAuth credentials
gws auth setup

# Step 2: log in (opens a URL — open it on your Mac browser, paste code back)
gws auth login
```

Requires a Google Cloud project with the following APIs enabled:
- Google Calendar API
- (optionally) Gmail, Drive, Sheets, Docs APIs

OAuth credentials are stored in `~/.config/gws/` and shared into the container
via the volume mount. No re-auth needed after container restarts.

## Restart container after auth

```bash
ssh pi@10.1.1.148 'cd ~/git_repo/nanobot && docker rm -f nanobot && docker compose up -d nanobot-gateway'
```

## Verify inside container

```bash
docker exec nanobot gws --version
docker exec nanobot gws calendar +agenda
```

## Agent usage

Once auth is complete, the nanobot agent can use `exec` to call `gws` directly:

```
gws calendar +agenda
gws calendar events list --params '{"calendarId": "primary", "maxResults": 10}'
gws calendar +insert
gws gmail +triage
gws drive files list --params '{"pageSize": 5}'
```

## Upgrading gws

```bash
# On RPI host — container picks up the new binary automatically (volume mount)
NEW_VERSION=v0.22.5  # change to latest
curl -L -o /tmp/gws.tar.gz https://github.com/googleworkspace/cli/releases/download/${NEW_VERSION}/google-workspace-cli-aarch64-unknown-linux-gnu.tar.gz
mkdir -p /tmp/gws_extract && tar -xzf /tmp/gws.tar.gz -C /tmp/gws_extract
sudo mv /tmp/gws_extract/gws /usr/local/bin/gws
rm -rf /tmp/gws_extract /tmp/gws.tar.gz
```
