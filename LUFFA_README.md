# Luffa Nanobot — Setup & Running Guide

A step-by-step guide to setting up the Luffa Nanobot with the Fake MCP server for simulating Luffa Card purchases.

---

## Prerequisites

- Python 3.11+
- A Luffa account with a bot secret key
- An LLM API key (OpenRouter recommended)

---

## Step 1 — Clone & Install

```bash
git clone https://github.com/NirajKulkarnii/nanobot.git
cd nanobot
pip install -e .
```

---

## Step 2 — Initialize Nanobot

Run the onboard command to create the workspace and default config:

```bash
nanobot onboard
```

This creates:
- `~/.nanobot/config.json` — main config file
- `~/.nanobot/workspace/` — agent workspace (AGENTS.md, MEMORY.md, etc.)

---

## Step 3 — Configure the LLM Provider

Open `~/.nanobot/config.json` and add or merge the following two sections.

**Set your API key** (OpenRouter recommended for global users):

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

**Set your model and provider:**

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

> For vLLM (local), use `"provider": "vllm"` and set `"apiBase": "http://127.0.0.1:8001/v1"` under the `vllm` provider key. The model name must exactly match what `curl http://127.0.0.1:8001/v1/models` returns.

---

## Step 4 — Add the Luffa Fake MCP Server

Add the MCP server entry into the `tools.mcpServers` section of `~/.nanobot/config.json`:

```json
{
  "tools": {
    "mcpServers": {
      "luffa-fake-mcp": {
        "command": "./.venv/bin/python",
        "args": [
          "-u",
          "./mcp_server/luffa_mcp_server.py"
        ],
        "toolTimeout": 30
      }
    }
  }
}
```

> **Important:** Use the absolute path if the relative path doesn't work:
> ```bash
> realpath ./mcp_server/luffa_mcp_server.py
> # Then replace the args value with the full path shown
> ```

---

## Step 5 — Add Your User ID to the Fake MCP Database

Open `mcp_server/luffa_mcp_server.py` and find the `USERS` dictionary near the top. Add your Luffa user ID as a new entry:

```python
USERS = {
    "user_001": { ... },   # existing test user
    "user_002": { ... },   # existing test user

    # ── Add your own entry below ──────────────────────────
    "YOUR_LUFFA_USER_ID": {
        "name": "Your Name",
        "email": "you@example.com",
        "phone": "+1-555-0000",
        "dob": "1990-01-01",
        "address": "Your Address",
        "kyc_status": "verified",        # set to "verified" to test happy path
        "wallet_balance": 50.00,         # starting balance in USDT
        "currency": "USDT",
        "has_card": False,
    },
}
```

> Replace `YOUR_LUFFA_USER_ID` with the actual user ID Luffa sends in message payloads (e.g. your Luffa account ID).

---

## Step 6 — Enable the Luffa Channel

Add the Luffa channel config to `~/.nanobot/config.json` under `channels`:

```json
{
  "channels": {
    "luffa": {
      "enabled": true,
      "token": "YOUR_LUFFA_BOT_SECRET_KEY",
      "allowFrom": [
        "YOUR_LUFFA_USER_ID"
      ]
    }
  }
}
```

- `token` — your Luffa bot secret key from the Luffa developer/bot settings
- `allowFrom` — list of Luffa user IDs allowed to chat with this bot (whitelist)

---


## Step 7 — Start the Bot

```bash
nanobot gateway
```

The gateway will:
1. Connect to the Luffa channel using your bot secret key
2. Launch the `luffa_mcp_server.py` subprocess automatically
3. Register all 7 MCP tools
4. Start listening for messages from your Luffa user ID

---

## Step 9 — Test the Luffa Card Flow

Open the Luffa app and message your bot:

```
I want to apply for a Luffa Card
```

The bot will automatically run through the flow:

| Step | What happens |
|---|---|
| Automatic | Checks wallet balance via MCP |
| Automatic | Fetches card offers |
| Automatic | Verifies KYC status |
| Automatic | Checks if balance covers fee |
| **Pauses** | Shows fee and asks **YES / NO** |
| After YES | Checks profile, submits application |
| Done | Shows card number, expiry, app ID |

### Other test messages

| Message | Expected behaviour |
|---|---|
| `I want a Luffa Card` | Starts full flow |
| `top up 10` | Adds 10 USDT, resumes flow |
| `YES` | Confirms and applies (during Step 5) |
| `NO` | Cancels, no fee deducted |

---