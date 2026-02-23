---
name: setup
description: Run initial nanobot setup. Use when user wants to install, configure providers, set up chat channels, or deploy the gateway. Triggers on "setup", "install", "configure nanobot", "onboard", or first-time setup requests.
---

# nanobot Setup

Run setup steps automatically. Only pause when user action is required (OAuth login, pasting tokens, scanning QR codes). Use `AskUserQuestion` for all user-facing choices.

**Principle:** When something is broken or missing, fix it. Don't tell the user to go fix it themselves unless it genuinely requires their manual action (e.g. running `claude setup-token` in another terminal, scanning a QR code). If a dependency is missing, install it. If a config is wrong, fix it. Ask the user for permission when needed, then do the work.

**Config editing:** Always read `~/.nanobot/config.json` first, merge changes into existing config, write back. Never overwrite unrelated settings.

**Secrets policy:** OAuth tokens must NEVER be collected in chat — direct the user to run the auth command in another terminal. API keys and channel tokens CAN be collected via `AskUserQuestion` since they are user-provided credentials the user explicitly wants to configure.

**Idempotent:** Check state before each step. Skip what's already done, offer to reconfigure if user wants.

## 1. Prerequisites

Check requirements and fix what's missing:

```bash
python3 --version   # Need >= 3.11
docker --version    # Need Docker for containerized deploy
which nanobot       # Check if nanobot CLI is installed
```

- **Python < 3.11 or missing:** Inform user, suggest install method for their OS.
- **Docker missing/not running:**
  - Not installed: `AskUserQuestion: Docker is needed for containerized deployment. Install it?`
    - Linux: `curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER`
    - macOS: `brew install --cask docker`
  - Installed but not running: start it (`sudo systemctl start docker` on Linux, `open -a Docker` on macOS). Wait 15s, re-check with `docker info`.
- **nanobot not installed:** Check if we're in the nanobot repo directory.
  - In repo: `pip install -e .` (editable install for development)
  - Not in repo: `pip install nanobot-ai` or `uv tool install nanobot-ai`

## 2. Onboard

Run `nanobot onboard` to create config and workspace.

```bash
nanobot onboard
```

- If config already exists, choose "N" (refresh, keep existing values).
- If fresh install, it creates `~/.nanobot/config.json` and `~/.nanobot/workspace/`.
- Verify config exists after: `cat ~/.nanobot/config.json`

## 3. Provider Authentication

`AskUserQuestion: Which LLM provider do you want to use?`

Options:
- **Claude Code CLI (OAuth)** — Uses your Claude Code subscription. No API key needed.
- **OpenRouter** — Access to all models. Needs API key from openrouter.ai.
- **Anthropic** — Claude direct. Needs API key from console.anthropic.com.
- **Other** — Any provider from the supported list.

### Claude Code CLI (OAuth)

Claude Code uses OAuth — no API key or `providers` config entry needed. The token is read from the `CLAUDE_CODE_OAUTH_TOKEN` env var at runtime. The `providers.claude_code` section in config only has `enabled` (default: true) and an optional `model` override.

1. Check if `claude` CLI is installed: `which claude`
   - Not installed: inform user to install Claude Code CLI first (https://docs.anthropic.com/en/docs/claude-code)
2. Check if token already exists: `echo $CLAUDE_CODE_OAUTH_TOKEN`
   - If set, confirm with user: keep existing token or re-authenticate?
3. If no token: tell user to run `claude setup-token` **in another terminal** and come back when done.
   - **Do NOT collect the token in chat.**
   - `claude setup-token` prints a token starting with `sk-ant-oat...`
   - After user confirms they ran it, verify the token is accessible.
4. **Wire up the env var for nanobot to read it:**
   - **For Docker:** Ensure `docker-compose.yml` has `env_file: .env` in the gateway service. If not, add it. Then add the token to `.env` in the project root:
     ```bash
     echo "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-..." >> .env
     ```
     Make sure `.env` is in `.gitignore` (never commit secrets).
   - **For local/systemd:** Add to shell profile (`~/.bashrc` or `~/.zshrc`):
     ```bash
     export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat-..."
     ```
     Then `source ~/.bashrc` (or restart shell).
   - Verify: `echo $CLAUDE_CODE_OAUTH_TOKEN | head -c 10` should show `sk-ant-oat`
5. `AskUserQuestion: Which Claude model?` Options: claude-sonnet-4-20250514 (recommended, fast), claude-opus-4-5-20250414 (most capable).
6. Set model in config — read config, merge (only the model, no provider entry needed):
   ```json
   {
     "agents": {
       "defaults": {
         "model": "claude-code/claude-sonnet-4-20250514"
       }
     }
   }
   ```

### OpenRouter

1. `AskUserQuestion: What is your OpenRouter API key?` (get one at https://openrouter.ai/keys)
2. Read current config, merge the key:
   ```json
   {
     "providers": {
       "openrouter": {
         "apiKey": "sk-or-v1-xxx"
       }
     }
   }
   ```
3. `AskUserQuestion: Which model?` Suggest `anthropic/claude-sonnet-4-20250514` as default.

### Anthropic (direct)

1. Same pattern: user provides API key, write to config under `providers.anthropic.apiKey`.
2. Model: `claude-sonnet-4-20250514` default.

### Other providers

For any other provider in the supported list (deepseek, gemini, groq, minimax, etc.):
1. Ask for API key
2. Write to appropriate config field: `providers.<name>.apiKey`
3. Ask for model name or suggest a default

## 4. Channel Setup

`AskUserQuestion: Which chat channel(s) do you want to connect?`

Options: Telegram (recommended), Discord, WhatsApp, Slack, Feishu, DingTalk, Email, QQ, Mochat, None (CLI only for now)

### Telegram

1. Tell user: Open Telegram, search `@BotFather`, send `/newbot`, follow prompts, copy the token.
2. `AskUserQuestion: What is your Telegram bot token?` — Write to config.
3. `AskUserQuestion: What is your Telegram User ID?` (find in Telegram settings, without `@`)
4. Write to config:
   ```json
   {
     "channels": {
       "telegram": {
         "enabled": true,
         "token": "BOT_TOKEN",
         "allowFrom": ["USER_ID"]
       }
     }
   }
   ```

### Discord

1. Tell user: Go to https://discord.com/developers/applications, create app, add bot, enable MESSAGE CONTENT INTENT, copy bot token.
2. Tell user: Enable Developer Mode in Discord settings, right-click avatar, Copy User ID.
3. Collect bot token and user ID via `AskUserQuestion`.
4. Write to config:
   ```json
   {
     "channels": {
       "discord": {
         "enabled": true,
         "token": "BOT_TOKEN",
         "allowFrom": ["USER_ID"]
       }
     }
   }
   ```
5. Remind user to invite the bot: OAuth2 > URL Generator > Scopes: `bot` > Permissions: `Send Messages`, `Read Message History`.

### WhatsApp

1. Requires Node.js >= 18. Check: `node --version`. Install if missing:
   - Linux: `curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs`
   - macOS: `brew install node@22`
2. Tell user they'll need two terminals:
   - Terminal 1: `nanobot channels login` (scan QR with WhatsApp > Linked Devices)
   - Terminal 2: `nanobot gateway`
3. `AskUserQuestion: What is your phone number?` (format: +1234567890)
4. Write to config:
   ```json
   {
     "channels": {
       "whatsapp": {
         "enabled": true,
         "allowFrom": ["+1234567890"]
       }
     }
   }
   ```

### Slack

1. Tell user to create a Slack app at https://api.slack.com/apps (from scratch).
2. Guide: Socket Mode ON > generate App-Level Token (`xapp-...`), add bot scopes (`chat:write`, `reactions:write`, `app_mentions:read`), subscribe to events (`message.im`, `message.channels`, `app_mention`), enable Messages Tab, install to workspace, copy Bot Token (`xoxb-...`).
3. Collect bot token and app token via `AskUserQuestion`.
4. Write to config:
   ```json
   {
     "channels": {
       "slack": {
         "enabled": true,
         "botToken": "xoxb-...",
         "appToken": "xapp-...",
         "groupPolicy": "mention"
       }
     }
   }
   ```

### Feishu

1. Tell user: Visit https://open.feishu.cn/app, create app, enable Bot, add `im:message` permission, add `im.message.receive_v1` event with Long Connection mode, get App ID and App Secret, publish app.
2. Collect App ID and App Secret via `AskUserQuestion`.
3. Write to config (`encryptKey` and `verificationToken` are optional for Long Connection mode):
   ```json
   {
     "channels": {
       "feishu": {
         "enabled": true,
         "appId": "cli_xxx",
         "appSecret": "xxx",
         "encryptKey": "",
         "verificationToken": "",
         "allowFrom": []
       }
     }
   }
   ```

### DingTalk

1. Tell user: Visit https://open-dev.dingtalk.com/, create app, add Robot capability, toggle Stream Mode ON, get AppKey and AppSecret.
2. Collect credentials via `AskUserQuestion`.
3. Write to config:
   ```json
   {
     "channels": {
       "dingtalk": {
         "enabled": true,
         "clientId": "APP_KEY",
         "clientSecret": "APP_SECRET"
       }
     }
   }
   ```

### Email

1. Tell user to create a dedicated email account (e.g. Gmail with App Password: enable 2-Step Verification, then create an App Password at https://myaccount.google.com/apppasswords).
2. Collect IMAP/SMTP settings and allowed sender addresses via `AskUserQuestion`.
3. Write to config:
   ```json
   {
     "channels": {
       "email": {
         "enabled": true,
         "consentGranted": true,
         "imapHost": "imap.gmail.com",
         "imapPort": 993,
         "imapUsername": "my-nanobot@gmail.com",
         "imapPassword": "your-app-password",
         "smtpHost": "smtp.gmail.com",
         "smtpPort": 587,
         "smtpUsername": "my-nanobot@gmail.com",
         "smtpPassword": "your-app-password",
         "fromAddress": "my-nanobot@gmail.com",
         "allowFrom": ["your-real-email@gmail.com"]
       }
     }
   }
   ```

### QQ

1. Tell user: Visit https://q.qq.com, register as developer, create bot, get AppID and AppSecret.
2. Tell user to set up sandbox for testing.
3. Collect credentials via `AskUserQuestion`.
4. Write to config:
   ```json
   {
     "channels": {
       "qq": {
         "enabled": true,
         "appId": "APP_ID",
         "secret": "APP_SECRET"
       }
     }
   }
   ```

### Mochat

1. Simplest option — tell user they can ask nanobot itself to set it up:
   > Send this to nanobot: `Read https://raw.githubusercontent.com/HKUDS/MoChat/refs/heads/main/skills/nanobot/skill.md and register on MoChat. My Email account is xxx@xxx Bind me as your owner and DM me on MoChat.`
2. Or collect `claw_token` and `agent_user_id` manually and write to config:
   ```json
   {
     "channels": {
       "mochat": {
         "enabled": true,
         "base_url": "https://mochat.io",
         "socket_url": "https://mochat.io",
         "socket_path": "/socket.io",
         "claw_token": "claw_xxx",
         "agent_user_id": "6982abcdef",
         "sessions": ["*"],
         "panels": ["*"],
         "reply_delay_mode": "non-mention",
         "reply_delay_ms": 120000
       }
     }
   }
   ```

## 5. Deploy

`AskUserQuestion: How do you want to run nanobot?`

Options:
- **Docker (recommended)** — containerized, auto-restart
- **Local** — run directly with `nanobot gateway`
- **systemd service** — run as a background Linux service

### Docker

```bash
docker compose up -d --build nanobot-gateway
```

Verify:
```bash
docker compose ps
docker compose logs --tail 20 nanobot-gateway
```

If build fails: read logs, diagnose, fix, retry.

### Local

```bash
nanobot gateway
```

Note: this runs in foreground. Suggest Docker or systemd for persistent deployment.

### systemd service (Linux)

1. Find nanobot path: `which nanobot`
2. Create `~/.config/systemd/user/nanobot-gateway.service` (replace ExecStart path if needed):
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
3. Enable and start:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now nanobot-gateway
   ```
4. User services only run while logged in. For unattended operation:
   ```bash
   loginctl enable-linger $USER
   ```

## 6. Verify

Run verification checks:

```bash
nanobot status
```

For Docker:
```bash
docker compose ps
docker compose logs --tail 30 nanobot-gateway
```

Check for:
- Provider shows as configured (API key or OAuth token detected)
- Channels show as enabled
- Gateway is running and accepting connections
- No errors in logs

If something is wrong, diagnose and fix. Common issues:
- **Provider not detected:** Check config.json has the right key under `providers`.
- **Channel failing:** Check token/credentials are correct, bot has required permissions.
- **Gateway won't start:** Check port 18790 is free, Docker is running.

Tell user to test by sending a message in their configured channel.

## Troubleshooting

**`claude setup-token` didn't set the env var:** The token may need to be exported. Check `~/.claude/` for credential files. The user may need to restart their shell or source the profile.

**Docker build fails:** Run `docker compose build --no-cache nanobot-gateway` for a clean build.

**Gateway crashes on startup:** Check `docker compose logs nanobot-gateway`. Usually a config issue — missing required fields or invalid JSON.

**Bot doesn't respond:** Check `allowFrom` — if set, only listed user IDs can interact. Empty list means allow everyone.
