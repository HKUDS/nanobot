---
name: create-instance
description: "Create a new nanobot instance with separate config and workspace. Use when the user wants to set up a new bot for a different channel, persona, or purpose."
---

# Create Instance

Set up a new nanobot instance with its own config and workspace.

## When to Use

When the user wants to create a new bot instance — typically for a different channel (Telegram, Discord, WeChat, etc.) or with different settings.

## Steps

1. **Collect information from the user** (ask one at a time if not already provided):
   - **Instance name** (required): a short identifier like `telegram-bot`, `discord-bot`
   - **Channel type** (required): e.g. `telegram`, `discord`, `weixin`, `feishu`, `slack`
   - **Model** (optional): LLM model to use. Defaults to the same model as the current instance.

2. **Do NOT collect sensitive information** in the chat (API keys, bot tokens, secrets). API keys are automatically copied from the current instance. Channel-specific tokens (e.g. `telegram.token`) still need to be filled in manually.

3. **Run the creation script** using the exec tool — always pass `--inherit-config` with the current instance's config path so API keys are copied:

```bash
python D:/path/to/nanobot/skills/create-instance/scripts/create_instance.py --name <name> --channel <channel> --inherit-config ~/.nanobot/config.json [--model <model>] [--config-dir <path>]
```

**Path rules (critical on Windows):**
- Use **forward-slash absolute paths** to the script, e.g. `D:/path/to/create_instance.py`
- Do **NOT** wrap paths in quotes — the exec tool will mangle them
- Do **NOT** use `cd` — the exec tool ignores it; working directory stays as workspace
- Do **NOT** use backslash paths like `D:\path` — they will fail

Use `~/.nanobot/config.json` as the `--inherit-config` path unless the current instance uses a custom config location.

4. **Report results to the user**:
   - Where the config and workspace were created
   - Which fields they need to fill in (the script will list them)
   - The command to start the instance: `nanobot gateway --config <config-path>`

## Examples

User: "help me create a Telegram bot" (or similar request)

→ Ask for an instance name if not obvious from context
→ Ask which model to use (optional, can skip if user doesn't care)
→ Run: `python D:/path/to/nanobot/skills/create-instance/scripts/create_instance.py --name telegram-bot --channel telegram --inherit-config ~/.nanobot/config.json`
  (Replace `D:/path/to/nanobot` with the actual nanobot source directory)
→ Tell user: config created at `~/.nanobot-telegram/config.json`, fill in `channels.telegram.token`, then start with `nanobot gateway --config ~/.nanobot-telegram/config.json`
