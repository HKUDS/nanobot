# Zalo Channel Integration

This document details the setup and implementation of the Zalo Channel for Nanobot.

## 1. Overview

The Zalo Channel enables `nanobot` to receive messages from a Zalo Official Account (OA) and reply using the Zalo Bot API. It operates in **Webhook Mode**, meaning Zalo sends HTTP POST requests to a server hosted within Nanobot.

## 2. Setup Guide

### prerequisites
1.  **Zalo BOT**: You need an active Official Account and read informations from [bot.zapps.me](https://bot.zapps.me).
2.  **Zalo Developer App**: Created at [developers.zalo.me](https://developers.zalo.me/).
3.  **Bot Token**: A static access token from [bot.zaloplatforms.com](https://bot.zaloplatforms.com/).
4.  **Webhook Secret**: Also from the Zalo Bot Platform settings.
5.  **Python_ZALO_BOT**: Access from [python-zalo-bot](https://pypi.org/project/python-zalo-bot/).
  
### Configuration
Add the following to your `data/config.json` file:

```json
"zalo": {
  "enabled": true,
  "botToken": "YOUR_STATIC_ACCESS_TOKEN",
  "webhookSecret": "YOUR_SECRET_TOKEN",
  "webhookPath": "/webhooks/zalo",
  "webhookHost": "0.0.0.0",
  "webhookPort": 5005
}
```

### exposing Local Server
For development, use `ngrok` to expose your local port (5005) to the internet:

```bash
ngrok http 5005
```

**Zalo Webhook URL**: Set this in your bot settings to:
`https://<your-ngrok-domain>.ngrok-free.app/webhooks/zalo`

## 3. Code Architecture

### `nanobot/channels/zalo.py`
The implementation includes:
- **Decentralized Config**: `ZaloConfig` is defined locally within the plugin, inheriting from `Base` for automatic camelCase support.
- **Webhook Server**: A `FastAPI` application (via `uvicorn`) listening on `/webhooks/zalo`.
- **SDK Integration**: Uses `python-zalo-bot` for event parsing and message sending.
- **Security**: Verifies the `X-Bot-Api-Secret-Token` header.
- **Advanced Features**: Supports periodic typing indicators and visual emphasis via Unicode formatting.

### Troubleshooting
- **ModuleNotFoundError**: Ensure you install dependencies with `uv sync --extra zalo`.
- **404 Not Found**: Ensure your Zalo Webhook URL includes the path `/webhooks/zalo`.
