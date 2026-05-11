# Implementation Plan: Multi-Tenant Auth + Per-User State

## Overview

Convert nanobot from single-tenant (`~/.nanobot/`) to multi-user. Each WebUI user gets an isolated profile, workspace, sessions, memory, media, tool-state. One shared gateway process serves all users; per-user state is carved out by `user_id`. Channels (Telegram/Slack/etc.) stay admin-scoped for v1 — only the WebUI is per-user.

Auth: email + password, local accounts (argon2id), no SMTP, no email verification, no self-serve reset. Signup open; admin promotion via CLI (`nanobot user promote <email>`). LLM provider keys remain system-wide in `~/.nanobot/config.json` (admin-supplied).

Migration: on startup with multi-tenant build, if legacy single-user layout detected (`~/.nanobot/sessions/`, `workspace/`, `memory/` present and `~/.nanobot/users/` absent), archive existing dir to `~/.nanobot.legacy.<ISO-date>/` and start fresh. Loud warning to operator with copy-paste recovery instructions.

## Decisions Locked

| Decision | Choice | Source |
|---|---|---|
| Process model | Shared agent, per-user state | User Q1 |
| Auth method | Email + password (local) | User Q2 |
| Key model | Admin-supplied, system-wide | User Q3 |
| Channel scope | Admin-only for v1 | User Q4 |
| Signup | Open; admin promotion via CLI | User Q5 |
| Email features | None in v1 | User Q6 |
| Migration | Fresh start, archive legacy | User Q7 |

## Architecture

### Per-User Filesystem Layout

```
~/.nanobot/
  config.json                       # admin/system-wide (LLM keys, channel tokens)
  auth.db                           # SQLite: users, web_sessions, audit_log
  bridge/                           # global WhatsApp bridge (admin)
  cron/                             # global gateway cron (heartbeat, dream)
  logs/                             # global gateway logs
  users/
    <uid>/                          # uid = ULID, stable across renames
      profile.json                  # email, display_name, role, created_at
      workspace/
      sessions/
      memory/
      media/
      tool-results/
      file_state/
```

Admin is a role flag on the user row — admin's data lives under `users/<uid>/` like any other user.

### Identity Threading

1. **HTTP login** — `POST /auth/login {email, password}` → argon2 verify → server issues `nanobot_session` HttpOnly cookie (32-byte random, SameSite=Lax, Secure when TLS) and persists `(sha256(token), user_id, expires_at)` in `auth.db.web_sessions`.
2. **WebSocket handshake** — gateway upgrade path reads `Cookie: nanobot_session=…`, verifies token against `auth.db`, attaches `user_id` to the connection. Existing static-token / `?token=` flow retained for admin / non-browser clients.
3. **Inbound message** — websocket channel sets `InboundMessage.user_id` (new optional field). Loop resolves a `UserContext` per inbound and threads it through `AgentRunner` and tool invocations.
4. **Tool / path resolution** — new `UserContext` carries `user_id` + resolved paths. Helpers in `nanobot/config/paths.py` accept an optional `UserContext` and branch: with ctx → `~/.nanobot/users/<uid>/<subdir>`, without ctx (CLI, channel-admin path) → legacy global path (preserved for channel-side behavior).

### What Stays Global vs Per-User

| Resource | Scope | Reason |
|---|---|---|
| `config.json` (LLM keys, channels, agent defaults) | Global | Admin-supplied (Q3); channels admin-only (Q4) |
| Bridge (WhatsApp) | Global | Channels admin-scoped |
| Channel inbound (Telegram/Slack/Discord) | Global | Q4 — admin-only for v1 |
| Gateway cron (heartbeat, dream) | Global | System jobs |
| WebUI sessions, memory, workspace, media | Per-user | Core isolation requirement |
| Tool-results, file_state | Per-user | Per-conversation artifacts |
| `auth.db` | Global | User identity store |

### Auth DB Schema (SQLite)

```sql
CREATE TABLE users (
  id              TEXT PRIMARY KEY,           -- ULID
  email           TEXT UNIQUE NOT NULL COLLATE NOCASE,
  password_hash   TEXT NOT NULL,              -- argon2id
  display_name    TEXT,
  role            TEXT NOT NULL DEFAULT 'user',  -- 'user' | 'admin'
  created_at      INTEGER NOT NULL,
  last_login_at   INTEGER,
  disabled        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE web_sessions (
  token_hash      TEXT PRIMARY KEY,           -- sha256(token); raw token never stored
  user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at      INTEGER NOT NULL,
  expires_at      INTEGER NOT NULL,
  last_seen_at    INTEGER NOT NULL,
  user_agent      TEXT,
  ip              TEXT
);
CREATE INDEX idx_sessions_user ON web_sessions(user_id);
CREATE INDEX idx_sessions_expires ON web_sessions(expires_at);

CREATE TABLE audit_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  ts              INTEGER NOT NULL,
  actor_user_id   TEXT,                       -- nullable for failed login
  event           TEXT NOT NULL,              -- 'login.ok','login.fail','signup','promote','reset','delete','session.expire'
  target_user_id  TEXT,
  ip              TEXT,
  detail          TEXT
);
```

Password hashing: **argon2id** via `argon2-cffi` (new dep). Bcrypt acceptable fallback if argon2 wheel missing on target arch.

Session token: 32 random bytes → urlsafe-b64 → stored as `sha256(token)` server-side. TTL 30 days, sliding on activity. Logout deletes row.

### Threat Model Quickref

- **Brute-force login** → rate limit `/auth/login` to 5 attempts/min/IP (in-memory token bucket; fine for single-instance gateway).
- **Session theft** → HttpOnly + SameSite=Lax cookie; Secure when TLS; rotate token on privilege elevation.
- **Mass enumeration via signup** → registration open per Q5; mitigate with rate limit + CAPTCHA hook stub (no-op v1) for later.
- **Path traversal** → all user-scoped paths derived from validated ULID, never from raw client input.
- **CSRF on /auth/login & /auth/signup** → double-submit token pattern; cookie SameSite=Lax already mitigates most cases.
- **Cross-user data leak via tool registry** → registry rebuilt per request from `UserContext`, not memoized globally.

### Dependency Graph

```
auth_schema (SQLite migration)
    │
    ├── AuthService (hash/verify, session mint/verify, audit)
    │       │
    │       ├── HTTP routes: /auth/signup /auth/login /auth/logout /auth/me
    │       │       └── WebUI login/signup pages
    │       │
    │       └── WS handshake auth (cookie → user_id)
    │               └── InboundMessage.user_id
    │                       └── UserContext (path resolver)
    │                               ├── SessionManager (per-user history root)
    │                               ├── Memory store (per-user)
    │                               ├── Workspace tools (filesystem/shell/cron/file_state)
    │                               ├── Media uploads (per-user dir)
    │                               └── Tool registry instantiation (per-request)
    │
    ├── CLI: nanobot user {list,create,promote,demote,reset-password,delete}
    │
    └── Startup migration: legacy detect → archive
```

### Vertical Slices

Each slice is a thin end-to-end path — all layers touched for one scenario, verified before moving on.

---

## Slice A — Thin Slice: One User, Cookie Auth, Isolated Sessions

**Goal:** A test user created via CLI can log in via WebUI, send a chat message, and have that message land in `~/.nanobot/users/<uid>/sessions/` — not `~/.nanobot/sessions/`.

**Tasks A1–A6 (see todo.md).** Touches every layer at minimum depth:

- SQLite schema + AuthService stub (no admin role logic yet — just user/session)
- `/auth/login` + `/auth/logout` + `/auth/me` HTTP routes on gateway
- Cookie-based WS handshake auth (Cookie → user_id) — keep static token fallback for admin tooling
- `UserContext` + `paths.py` ctx-aware helpers
- `SessionManager` accepts UserContext
- WebUI login page + auth context

**Verification:** integration test creates user → logs in → opens WS → sends message → asserts session file exists under user dir AND NOT under legacy global dir. Manual smoke via webui at `localhost:5173`.

**Checkpoint:** human review before Slice B. Path-resolution change is the biggest blast radius; confirm scope didn't sprawl beyond planned files.

## Slice B — Multi-User: Signup + Two Users Isolated

**Goal:** Two users sign up via WebUI, log in concurrently, cannot see each other's session list / messages / files.

**Tasks B1–B4.** Adds:

- `/auth/signup` HTTP route
- WebUI signup page + auth context (login state, logout button)
- Rate limit on `/auth/login` + `/auth/signup`
- Tests: concurrent user isolation, session list scoped to caller

**Verification:** integration test with two `httpx.AsyncClient` instances signing up, logging in, asserting non-overlapping session lists. Manual smoke: two private windows, sign up as A and B, send messages, confirm separate histories.

**Checkpoint:** human review before Slice C — confirm UX & route protection feel right.

## Slice C — Per-User Tool State + Memory + Media

**Goal:** All tools that previously wrote to `~/.nanobot/*` now write under `~/.nanobot/users/<uid>/`. Memory consolidation runs per-user. Media uploads namespaced.

**Tasks C1–C5.** Wires `UserContext` into:

- Filesystem / shell / read / write / edit / list tools (workspace root)
- Memory store + Dream cycle (per-user keyspace, scheduler still global)
- Media dir resolution in WS channel (`get_media_dir` ctx-aware)
- Tool-results dir (`_TOOL_RESULTS_DIR` in `utils/helpers.py`)
- File-state store (`file_state_store.for_session` already keyed — audit for cross-user safety)

MCP, cron, subagent, my_tool: audit but leave per-user wiring as deferred work unless trivial.

**Verification:** integration test — two users invoke filesystem tools, assert files land in respective workspaces. Memory dream cycle test asserts per-user keys. Manual smoke: user A creates `/notes.md`; user B cannot see it via WebUI file picker or shell tool.

**Checkpoint:** human review before Slice D — this is where tool-registry refactor either stays surgical or sprawls. Re-evaluate scope.

## Slice D — Admin CLI + Role + Admin Page

**Goal:** Operator manages users from CLI. Admin role exists and gates an admin-only page.

**Tasks D1–D4.** Adds:

- `nanobot user list|create|promote|demote|reset-password|delete` subcommands
- Role check middleware on gateway HTTP routes
- `/admin/users` JSON endpoint + minimal WebUI admin page (table of users, disable toggle, role badge)
- Audit log writes on every admin action

**Verification:** unit tests per CLI subcommand. Integration test: non-admin user gets 403 on `/admin/users`. CLI smoke: create, promote, list, demote, delete a test account.

**Checkpoint:** human review before Slice E.

## Slice E — Migration + Hardening + Docs

**Goal:** Multi-tenant build is safe to deploy on a box with existing single-user state. Operator gets a clear migration path. Security knobs documented.

**Tasks E1–E5.** Adds:

- Startup migration: detect legacy layout → archive `~/.nanobot/` → `~/.nanobot.legacy.<ISO-date>/` with loud log; leave `auth.db`, `users/`, `config.json` re-created blank
- Operator override env `NANOBOT_SKIP_LEGACY_MIGRATION=1` to disable
- Update `docs/configuration.md` + `docs/deployment.md` with multi-user section
- New `docs/auth.md` covering operator setup, CLI commands, threat model summary
- `argon2-cffi` added to `pyproject.toml`; CI lint + tests green
- `.agent/security.md` updated to note multi-tenant boundaries

**Verification:**

- Migration test: temp dir with synthetic legacy state → startup → assert archive created and fresh tree exists.
- Skip-flag test.
- Doc lint: links resolve.
- Full test suite green; `ruff check nanobot/`; webui `bun run test` + `bun run build` clean.

**Checkpoint:** final human review. Merge to a feature branch (`feature/multi-tenant-auth`), open PR against `nightly` per CONTRIBUTING.md.

---

## Out of Scope (v1)

Deferred — call out in PR description, file follow-up issues:

- Email verification, password reset email, magic links (no SMTP per Q6)
- Per-user channels (Telegram/Slack token per user) — Q4 v1 = admin-only
- Per-user BYOK LLM keys — Q3 v1 = admin-supplied
- Per-user cron jobs
- SSO / OAuth providers (Google/GitHub) — scaffolding NOT included; defer to v2
- Quotas / rate limits per user (only auth-endpoint rate limit in v1)
- Real-time presence ("user A is typing")
- Team / org / workspace concepts
- Per-user MCP server allowlist
- Audit log UI (rows exist, no admin view in v1)

## Test Strategy

- **Unit** — AuthService (hash, verify, session mint/verify/expire), path helpers (ctx vs no-ctx), CLI command parsers.
- **Integration** — full HTTP/WS auth flow, cross-user isolation, migration script, role enforcement. Use existing `pytest-asyncio` + `aiohttp` test infra; spin gateway on ephemeral port.
- **WebUI** — vitest for login/signup form validation, auth context state machine, route protection. Manual smoke per slice in browser.
- **Security** — explicit tests for: argon2 verify, brute-force rate limit, cookie flags, path-traversal on user_id input, session expiry, cross-user data fetch returns 403/404.

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Path-resolution refactor leaks legacy global writes | M | H | Add a debug logger warning when `get_*_dir()` is called without ctx during a user-request lifecycle. Burn-down list in tests. |
| Concurrent migration races (gateway + CLI both start at once) | L | H | `filelock` (already a dep) on `~/.nanobot/.migration.lock`. |
| Argon2 wheel missing on target arch | M | M | Bcrypt fallback behind feature flag; documented in deploy guide. |
| WS reconnect drops user identity | M | M | WS handshake re-reads cookie on every connect; cookie persists, identity recovers. |
| Tool registry caches across users | H | H | Build registry **per-request** from UserContext; never cache at module level. Slice C explicit test. |
| Channels accidentally inherit user state | L | M | Channels keep using legacy global paths; do NOT pass UserContext to channel adapters in v1. |

## File Touch Estimate

| Area | New | Modified | Notes |
|---|---|---|---|
| `nanobot/auth/` | 4 (service.py, schema.py, routes.py, __init__.py) | 0 | New module |
| `nanobot/config/paths.py` | 0 | 1 | Ctx-aware helpers |
| `nanobot/cli/commands.py` + new `nanobot/cli/user.py` | 1 | 1 | CLI subcommands |
| `nanobot/channels/websocket.py` | 0 | 1 | Cookie auth + user_id attach |
| `nanobot/agent/loop.py` | 0 | 1 | Thread UserContext (small) |
| `nanobot/agent/runner.py` | 0 | 1 | Accept UserContext (small) |
| `nanobot/session/manager.py` | 0 | 1 | Ctx-aware history root |
| `nanobot/agent/memory.py` | 0 | 1 | Ctx-aware paths |
| `nanobot/agent/tools/*` | 0 | ~5 | Ctx propagation |
| `nanobot/utils/helpers.py` | 0 | 1 | Ctx-aware tool-results dir |
| `webui/src/auth/` | ~4 | 0 | LoginPage, SignupPage, AuthContext, route guard |
| `webui/src/lib/api.ts` | 0 | 1 | Wire login/logout/me |
| `webui/src/App.tsx` | 0 | 1 | Auth gating |
| `tests/auth/` | ~5 | 0 | New test files |
| `docs/auth.md` | 1 | 0 | New |
| `docs/configuration.md`, `docs/deployment.md` | 0 | 2 | Multi-user sections |
| `pyproject.toml` | 0 | 1 | argon2-cffi dep |

Rough order: ~20 new files, ~20 modified. Plan size is on the larger end — slice gates prevent it landing as one mega-PR.

## Success Criteria

The change ships when:

1. Two users can sign up via WebUI and operate concurrently with zero state overlap.
2. `nanobot user list/create/promote/demote/reset-password/delete` all work end-to-end.
3. Migration is safe on a box with existing single-user state — legacy archive intact, fresh tree empty, operator instructions printed.
4. Test suite green: `pytest`, `ruff check`, `bun run test`, `bun run build`.
5. Manual smoke: two private windows; sign up A and B; chat in each; verify isolation in files, sessions, memory dir.
6. No regression in CLI (`nanobot agent`) or chat channels (Telegram/Slack still work, admin-scoped).
7. `.agent/design.md` invariants preserved — `loop.py` / `runner.py` diffs minimal and justified.
