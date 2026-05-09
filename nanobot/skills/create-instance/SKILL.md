---
name: create-instance
description: "Create a new nanobot instance with separate config and workspace. Use when the user wants to set up a new bot, create a new instance for a different channel, persona, or purpose. Triggers on: create instance, new bot, set up bot, add bot, create telegram/discord/feishu/slack/wechat/wecom/dingtalk/qq/email/matrix/msteams/whatsapp bot, multi-instance setup."
---

# Create Instance

Set up a new nanobot instance with its own config and workspace.

## Steps

1. **Collect information** (ask one at a time if not already provided):
   - **Instance name** (required): short identifier, e.g. `telegram-bot`, `work-slack`
   - **Channel type** (required): see table below
   - **Model** (optional): LLM model, defaults to current instance

2. **Do NOT collect secrets** in the chat (API keys, bot tokens). API keys are automatically inherited from the current instance via `--inherit-config`. Channel-specific tokens must be filled in manually after creation.

3. **Run the creation script**:

```bash
python <skill-dir>/scripts/create_instance.py --name <name> --channel <channel> --inherit-config <current-config>
```

- `<skill-dir>` — the directory containing this SKILL.md
- `<current-config>` — current instance's config path, typically `~/.nanobot/config.json`
- Optional: `--model <model>`, `--config-dir <path>`

**Exec tool constraints:**
- Use forward-slash paths (works on all platforms)
- Do not wrap paths in quotes
- Do not use `cd`; pass the full script path directly

4. **Report results** to the user:
   - Config and workspace paths (script outputs them)
   - Required fields to fill in (script lists them)
   - Start command: `nanobot gateway --config <config-path>`

## Available Channels

| Channel | Key | Required Fields |
|---------|-----|-----------------|
| Telegram | `telegram` | token |
| Discord | `discord` | token |
| Feishu / Lark | `feishu` | app_id, app_secret |
| DingTalk | `dingtalk` | client_id, client_secret |
| Slack | `slack` | bot_token, app_token |
| WeCom | `wecom` | bot_id, secret |
| WeChat OA | `weixin` | token |
| WhatsApp | `whatsapp` | bridge_token |
| QQ | `qq` | app_id, secret |
| Email | `email` | imap_host, imap_username, imap_password, smtp_host, smtp_username, smtp_password, from_address |
| Matrix | `matrix` | user_id, password or access_token |
| MS Teams | `msteams` | app_id, app_password, tenant_id |
| MoChat | `mochat` | claw_token |
| WebSocket | `websocket` | token |

For detailed channel configuration including optional fields, see `references/channels.md`.

## Troubleshooting

- **"Unknown channel"**: Channel name must match the Key column exactly. Run the script without arguments to see usage.
- **"Config already exists"**: Use a different `--name` or `--config-dir` to create in a new location.
- **Port conflicts**: The script auto-assigns free ports for gateway and API if defaults are in use.
