# Nanobot — Dokploy Template

One-click Dokploy deployment for [nanobot](https://github.com/HKUDS/nanobot) gateway + WebUI.

## Quick Start

1. In Dokploy, create a Compose service → Advanced → Import → paste this template's Base64 payload.
2. Set `ANTHROPIC_API_KEY` under **Environment** to your Anthropic API key.
3. Deploy → the WebUI is available at your Dokploy reverse-proxy domain, or at `http://<host>:8765` for direct access.

The WebUI token is pre-filled with a random password — copy it from the Environment variables after import.

## ⚠️ LLM Unavailable Without an API Key

This template ships with an empty `ANTHROPIC_API_KEY`. The gateway will start, but the agent cannot call an LLM until you set a real key in the Dokploy service Environment.

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Single-service deploy: gateway + WebUI on port 8765 |
| `template.toml` | Domains, env, and variable definitions for Dokploy import |
| `dokploy-config.json` | First-boot config (copied to `~/.nanobot/config.json`) |
| `meta.json` | Template metadata for the Dokploy catalog |
| `README.md` | This file |

## Architecture

- **Gateway** health endpoint: internal only (127.0.0.1:18790)
- **WebUI** via WebSocket channel: 0.0.0.0:8765, accessible via Dokploy reverse-proxy domain
- **Data** persists in the `nanobot_data` named volume at `/home/nanobot/.nanobot`
- **Config** is initialised from `dokploy-config.json` on first boot; subsequent edits in `~/.nanobot/config.json` survive restarts
