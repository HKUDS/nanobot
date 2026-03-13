# Zalo Channel Integration

This document details the setup and implementation of the Zalo Channel for Nanobot.

## 1. Overview

The Zalo Channel enables `nanobot` to receive messages from a Zalo Official Account (OA) and reply using the Zalo Bot API. It operates in **Webhook Mode**, meaning Zalo sends HTTP POST requests to a server hosted within Nanobot.

## 2. Setup Guide

### prerequisites
1.  **Zalo OA**: You need an active Official Account.
2.  **Zalo Developer App**: Created at [developers.zalo.me](https://developers.zalo.me/).
3.  **Bot Token**: A static access token from [bot.zaloplatforms.com](https://bot.zaloplatforms.com/).
4.  **Webhook Secret**: Also from the Zalo Bot Platform settings.

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
- **Webhook Server**: A `FastAPI` application listening on `/webhooks/zalo`.
- **Event Handling**: Parses incoming JSON payloads (`message.text.received`, `message.image.received`).
- **Security**: Verifies the `X-Bot-Api-Secret-Token` header.
- **API Client**: Uses `httpx` to call the Zalo Bot API (`sendMessage`, `sendPhoto`).

### Troubleshooting
- **422 Unprocessable Content**: If you see this error, ensure `FastAPI` imports are at the module level in `zalo.py`. This fixed a known issue with type resolution.
- **404 Not Found**: Ensure your Zalo Webhook URL includes the path `/webhooks/zalo`.
