# Multi-Tenant Auth & Per-User State

Multi-tenant nanobot serves many users from a single gateway process. Each
WebUI account gets an isolated workspace, sessions, memory, media, and
tool-result spill area under `~/.nanobot/users/<user_id>/`. Chat channels
(Telegram, Slack, Discord, etc.) remain admin-scoped in v1; only the WebUI
is per-user.

This document is for **operators** standing up nanobot in a shared/multi-user
deployment. For end-user UX, see the WebUI directly.

## TL;DR

```bash
# 1. Start the gateway. On first run with legacy single-tenant state
#    on disk, the old layout is auto-archived to ~/.nanobot.legacy.<date>/.
nanobot gateway

# 2. Create the first admin (CLI is the only path until you have one).
nanobot user create admin@yourorg --role admin
# (you'll be prompted for a password; min 12 chars)

# 3. Open the WebUI. Sign in as that admin.
#    Use the "Users" link in the sidebar to manage other accounts.
```

The WebUI is gated by an HTTP-only `nanobot_session` cookie. The first
visitor sees a sign-in page; signup is open by default (single-team
deployments). Disable open signup at the reverse-proxy layer if needed.

---

## Filesystem Layout

```
~/.nanobot/
  config.json                       # admin / system-wide (LLM keys, channels)
  auth.db                           # SQLite: users, web_sessions, audit_log
  bridge/                           # WhatsApp bridge (admin)
  cron/                             # gateway-level cron (heartbeat, dream)
  logs/                             # gateway logs
  users/<user_id>/
    workspace/                      # per-user workspace (tools write here)
      memory/                       # per-user memory (MEMORY.md, history.jsonl)
      .nanobot/tool-results/        # tool-output spill files
    sessions/                       # per-user session JSONLs
    media/<channel>/                # per-user media uploads
    file_state/                     # per-user file read/write tracker (planned)
```

`<user_id>` is a 26-char Crockford-base32 ULID generated at signup. It is
stable across email or display-name changes and never appears in URLs.

**What stays global:** `config.json`, `bridge/`, channel adapters,
gateway-level cron jobs, `auth.db`. LLM provider API keys are
admin-supplied — there is no per-user BYOK in v1.

## Auth Mechanism

| Surface | Auth |
|---|---|
| WebUI HTTP/WS | `nanobot_session` cookie (HttpOnly, SameSite=Lax, Secure when TLS) |
| Chat channels | Existing channel-specific tokens (Telegram bot token, Slack OAuth, etc.) |
| Static-token WS clients | Legacy `?token=` query param (admin-only, kept for non-browser clients) |
| Operator CLI | Direct SQLite access — no remote auth |

Cookie minted at successful login or signup. Persisted server-side as
`sha256(token)` in `auth.db.web_sessions`; the raw token never lands on
disk. Sliding 30-day TTL — every request that successfully verifies the
cookie extends `expires_at`.

Passwords hashed with **argon2id** (`argon2-cffi`, time_cost=3,
memory_cost=64MB, parallelism=2). Wrong password and unknown email both
return the same generic error to avoid email enumeration.

## CSRF

Every response from the gateway sets a `nanobot_csrf` cookie if the request
didn't already carry one. The cookie is **not** HttpOnly so JS can read it.
State-changing requests (POST/PUT/PATCH/DELETE on `/auth/*` and `/admin/*`)
must echo the cookie value in the `X-CSRF-Token` header. The webui's
`authFetch` helper does this automatically. Combined with `SameSite=Lax`
on the session cookie, this protects against cross-origin POSTs (defence in
depth — the SameSite cookie alone already blocks the obvious vectors).

## Rate Limiting

In-memory token bucket per `(path, IP)`:

| Endpoint | Limit |
|---|---|
| `POST /auth/login`  | 5 attempts / minute |
| `POST /auth/signup` | 3 attempts / minute |

Over-limit responses return 429 with a `Retry-After: <seconds>` header.
Each trip writes a `ratelimit.trip` row to `audit_log`. Suitable for a
single-instance gateway behind a reverse proxy; replace with Redis-backed
limiter if you scale horizontally.

## CLI Reference

`nanobot user …` — operator-only, requires shell access to the host:

| Command | Description |
|---|---|
| `nanobot user list` | Tabular list of accounts (id, email, role, created, last login, disabled). |
| `nanobot user create <email> [--role admin] [--display-name "X"]` | Create an account. Prompts for password (min 12 chars). |
| `nanobot user promote <email-or-id>` | Grant admin role. |
| `nanobot user demote <email-or-id>` | Revoke admin role. |
| `nanobot user reset-password <email-or-id>` | Set new password and revoke all of the user's active sessions. |
| `nanobot user disable <email-or-id> [--off]` | Disable (default) or re-enable an account. Disabling also revokes live sessions. |
| `nanobot user delete <email-or-id> [--yes]` | Delete the account and cascade its sessions. **Filesystem data under `~/.nanobot/users/<id>/` is NOT removed automatically** — operator removes manually after auditing. |

Identifiers may be either an email or a ULID.

Every CLI command writes an `audit_log` row with `actor_user_id=NULL`
(system actor).

## Admin HTTP API

Authenticated as a non-disabled `role='admin'` user (cookie). State-changing
verbs require the CSRF header. Returns 401 (no session), 403 (not admin
or disabled).

| Endpoint | Description |
|---|---|
| `GET    /admin/users` | List all users (no pagination in v1; revisit at >100). |
| `POST   /admin/users/<id>/role`     `{role: "user" \| "admin"}` | Promote/demote. |
| `POST   /admin/users/<id>/disabled` `{disabled: bool}` | Disable cascades to session revocation. |
| `DELETE /admin/users/<id>` | Self-delete blocked with 400 — prevents operator lockout. |

## Legacy Migration

When you upgrade a host that ran pre-multi-tenant nanobot, the old layout
(`sessions/`, `workspace/`, `memory/` directly under `~/.nanobot`) is moved
out of the way on first gateway start:

```
~/.nanobot                ->  ~/.nanobot.legacy.YYYYMMDD-HHMMSS/
~/.nanobot/config.json    (preserved into the new ~/.nanobot)
~/.nanobot/users/         (created empty)
```

A loud warning prints to console with the rollback command:

```bash
mv ~/.nanobot.legacy.<date> ~/.nanobot
```

Skip the migration entirely with `NANOBOT_SKIP_LEGACY_MIGRATION=1` (useful
when running multiple gateway instances against shared state, or when
you've already manually migrated). Contention is guarded by a
`filelock` on `~/.nanobot/.migration.lock`.

## Threat Model Summary

| Risk | Mitigation |
|---|---|
| Brute-force login | 5/min/IP rate limit on `/auth/login`; argon2id is intentionally slow. |
| Session theft | HttpOnly + SameSite=Lax cookie; Secure when behind TLS. Logout deletes the row. |
| Email enumeration on login | Generic error response; constant-time hash even on unknown email. |
| Cross-origin CSRF | Double-submit `X-CSRF-Token` header + SameSite=Lax cookie. |
| Path traversal via user_id | All per-user paths derive from a ULID-validated UserContext, never raw input. |
| Cross-user data leak via tools | Tools (filesystem, shell, memory, media, tool-results) consult `current_user_ctx` ContextVar; per-user keying in `FileStateStore`. |
| Disabled-admin still has cookie | `_require_admin` blocks any admin route call from a disabled account; disable cascades to session revocation. |
| Self-lockout | `DELETE /admin/users/<id>` blocks self; UI disables self-row buttons. |

## Known Limitations (v1, deferred to follow-ups)

- **No SSO / OAuth** (Google, GitHub, Magic-link). Local accounts only.
- **No email verification or self-serve password reset.** Operator uses
  `nanobot user reset-password`. SMTP infra is out of scope for v1.
- **Per-user channels not supported.** Telegram/Slack/Discord stay
  admin-scoped. A v2 mapping (`/link` chat command + per-user bot tokens)
  is in the backlog.
- **No per-user LLM API keys (BYOK).** Admin keys are shared across users.
- **No per-user cron jobs.** `nanobot.agent.tools.cron` is gateway-level.
- **No per-user MCP allowlist.** MCP servers are admin-scoped.
- **Dream consolidation runs as a global cron job.** It does not
  iterate per-user `memory/` directories. A per-user dream cycle needs
  its own scheduler design.
- **Signed media URLs are not user-bound.** `_handle_media_fetch` validates
  the HMAC against the global media root. An attacker who can sign URLs
  for one user could fetch another's media. Per-user uploads land in
  distinct directories so the attack requires forging an HMAC, but the
  cookie-binding hardening is tracked.
- **`image_generation` and `message` tools** still bind to the gateway
  workspace; their per-user wiring lands alongside the signed-URL
  hardening above.
- **Memory directory layout** lives under `users/<uid>/workspace/memory/`
  (one level deeper than the `users/<uid>/memory/` shown in early plans)
  because `GitStore` tracks files relative to the workspace root.
- **Audit log has no UI.** Rows are written to `auth.db.audit_log`;
  query with sqlite3 directly.

## Operator Recovery Cheatsheet

| Situation | Recovery |
|---|---|
| Forgot the admin password | `nanobot user reset-password <email>` |
| Locked out (no admin exists) | `nanobot user create newadmin@x --role admin` |
| Need to inspect login attempts | `sqlite3 ~/.nanobot/auth.db "SELECT * FROM audit_log ORDER BY ts DESC LIMIT 50"` |
| Need to disable a noisy user | `nanobot user disable <email>` (revokes sessions immediately) |
| Want to wipe a user's data | `nanobot user delete <email> --yes` then `rm -rf ~/.nanobot/users/<id>/` |
| Roll back a bad legacy migration | `mv ~/.nanobot.legacy.<date> ~/.nanobot` |
