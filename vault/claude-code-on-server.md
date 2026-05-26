---
tags: [note, log, ops]
---

# Claude Code on sphelps.net via Telegram

Notes from the 2026-05-26 port of a local Claude Code session to the
server, reachable via Telegram. Files in this vault:

- [[claude-code-telegram.service]] — systemd user unit
- [[claude-tg-kill]] — stop service + set killswitch
- [[claude-tg-resume]] — clear killswitch + start service

## What's running

A long-lived Claude Code session on sphelps.net, plugged into a
dedicated Telegram bot via the official `claude-plugins-official/telegram`
plugin. The bot is exclusively polled from the server (no laptop race).

```
script (PTY)
  └─ claude --channels plugin:telegram@claude-plugins-official
       └─ bun run --cwd ~/.claude/plugins/cache/.../telegram/0.0.6 …
            └─ bun server.ts  ← owns the api.telegram.org long-poll
```

`cwd` is `~/vcs/coding/nanobot` — the bot acts on this repo by default.

## Bot token strategy

One bot token per session (Telegram long-polling is exclusive — only
one process can poll a given token at a time). The Claude Code bot is
distinct from Peewee's and Iroh's bots. Three bots, three @BotFather
tokens, no collisions.

## Why the unit looks weird

Three things bit us during setup:

1. **PTY required.** Headless claude with `StandardInput=null` auto-flips
   to `--print` mode and exits within ~3 s. Wrap in
   `script -qfec "<cmd>" /dev/null` to allocate a pty; claude thinks
   it's interactive and stays alive.
2. **`--resume` doesn't work headless.** Errors with "no deferred tool
   marker" or wants a positional prompt (which then makes it single-shot).
   So no session continuity across restarts — each restart is a fresh
   conversation. The prior transcript file is on disk at
   `~/.claude/projects/-home-sphelps-vcs-coding-nanobot/<uuid>.jsonl`
   and the bot can be asked to read it.
3. **MCP tool permissions.** Auto-mode classifier on the server denies
   MCP tool calls by default. Pre-allow the four Telegram MCP tools in
   `~/.claude/settings.json`:

   ```json
   "permissions": {
     "defaultMode": "auto",
     "allow": [
       "mcp__plugin_telegram_telegram__reply",
       "mcp__plugin_telegram_telegram__react",
       "mcp__plugin_telegram_telegram__edit_message",
       "mcp__plugin_telegram_telegram__download_attachment"
     ]
   }
   ```

## What we copied from the laptop

- `~/.claude.json` — user profile incl. `hasCompletedOnboarding: true`,
  numStartups, oauthAccount, tipsHistory. Without this, claude blocks
  at the first-run theme picker.
- `~/.claude/.credentials.json` — OAuth credential (mode 0600).
- `~/.claude/settings.json` — global settings.
- `~/.claude/plugins/{installed_plugins.json, known_marketplaces.json,
  plugin-catalog-cache.json}` — plugin registry.
- `~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.6/` —
  the plugin tree itself (avoids re-downloading via `/plugin install`).
- `~/.claude/channels/telegram/{.env, access.json, approved/<senderId>}`
  — bot token, allowlist, pairing approval.
- The current transcript file (`-home-sphelps-vcs-coding-nanobot/…jsonl`).

Skipped (host-specific or auto-managed): `settings.local.json`, `cache/`,
`file-history/`, `history.jsonl`, `paste-cache/`, `session-env/`,
`sessions/`, `shell-snapshots/`.

## Lockdown

`access.json` is set to `dmPolicy: "allowlist"` after pairing. Only
the configured numeric user IDs can reach the bot. Strangers DMing it
get nothing — not even a pairing-code reply.

## Lingering

`loginctl enable-linger sphelps` was run so the unit survives the
operator's SSH logout. Reboot brings it back via the
`WantedBy=default.target`.

## Kill switch

To stop the bot:

```sh
~/.local/bin/claude-tg-kill
# touches ~/.claude/KILLSWITCH and stops the unit.
# ConditionPathExists=!KILLSWITCH in the unit means systemd refuses to
# (re)start it as long as the file exists.
```

To bring it back:

```sh
~/.local/bin/claude-tg-resume
# rm ~/.claude/KILLSWITCH && systemctl --user start claude-code-telegram.service
```

## To redeploy from this vault

```sh
cp vault/claude-code-telegram.service ~/.config/systemd/user/
cp vault/claude-tg-kill vault/claude-tg-resume ~/.local/bin/
chmod +x ~/.local/bin/claude-tg-kill ~/.local/bin/claude-tg-resume
systemctl --user daemon-reload
systemctl --user enable --now claude-code-telegram.service
```

## Open follow-ups

- **Session continuity across restarts.** Today: lost. Would need a way
  to make `--resume` work in headless mode. Worth filing upstream.
- **Channel race protection.** If a laptop session ever boots with
  `--channels` against the same bot token, both compete on long-poll
  and inbound DMs randomly land at one or the other. Mitigated only by
  discipline.
- **MCP tool permissions are wide-open.** The auto-allow list grants
  reply/react/edit/download unconditionally. Reasonable for a single-user
  bot you DM yourself; reconsider if you ever route untrusted senders
  to this same agent.
