# Todo: Multi-Tenant Auth + Per-User State

Sequential within a slice; each slice ends at a human-review checkpoint. See `tasks/plan.md` for architecture, decisions, threat model.

Branch: `feature/multi-tenant-auth` off `nightly` (per CONTRIBUTING.md).

Legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

---

## Slice A — Thin Slice: One User, Cookie Auth, Isolated Sessions

Walking-skeleton: cookie-auth end to end, one user, one path proven isolated. No UI signup yet, no admin role, no migration.

### A1. AuthDB schema + first migration

- [x] Add `argon2-cffi>=23.1.0,<24` to `pyproject.toml`
- [x] Create `nanobot/auth/__init__.py`, `nanobot/auth/schema.py` with SQL DDL from plan
- [x] On gateway startup, open `~/.nanobot/auth.db`, run `CREATE TABLE IF NOT EXISTS …`
- [x] Use `filelock` on `~/.nanobot/.auth-init.lock` during init to dodge races

**Acceptance:** `auth.db` exists with `users`, `web_sessions`, `audit_log` tables after gateway start. Re-running gateway is idempotent (no errors, no duplicate rows).

**Verify:** `sqlite3 ~/.nanobot/auth.db '.schema'` shows three tables and expected indices.

### A2. AuthService — argon2 hash, session mint/verify

- [x] `nanobot/auth/service.py`: class `AuthService` with `create_user(email, password, role='user')`, `verify_password(email, password)`, `mint_session(user_id, ua, ip)`, `verify_session(token)`, `revoke_session(token)`, `expire_sessions()`
- [x] Token: `secrets.token_urlsafe(32)`; persist `sha256(token)`
- [x] Argon2id parameters: time_cost=3, memory_cost=64MB, parallelism=2 (tune per benchmark)
- [x] Write audit_log row on every state change (login.ok/fail, signup, session.expire)

**Acceptance:** Unit tests pass: hash+verify roundtrip, wrong password rejected, session minted and verified, expired session rejected, revoked session rejected.

**Verify:** `pytest tests/auth/test_service.py -v` — all green.

### A3. Gateway HTTP auth routes — login, logout, me

- [x] `nanobot/auth/routes.py`: registers `/auth/login`, `/auth/logout`, `/auth/me` on existing gateway HTTP listener (port 18790)
- [x] `/auth/login` accepts JSON `{email, password}`, returns `{user: {...}}` and sets `nanobot_session` cookie (HttpOnly, SameSite=Lax, Secure if TLS, Max-Age=30d)
- [x] `/auth/logout` revokes session, clears cookie
- [x] `/auth/me` returns current user from cookie or 401
- [x] Generic error messages for login (no "user not found" vs "wrong password" distinction)

**Acceptance:** Integration test: create user via AuthService → POST /auth/login → cookie set → GET /auth/me returns user → POST /auth/logout → GET /auth/me returns 401.

**Verify:** `pytest tests/auth/test_routes.py -v`. `curl -i` smoke shows cookie flags.

### A4. UserContext + ctx-aware path helpers

- [x] `nanobot/auth/context.py`: dataclass `UserContext(user_id: str)` with methods `workspace_path()`, `sessions_dir()`, `memory_dir()`, `media_dir(channel=None)`, `tool_results_dir()`, `file_state_dir()`
- [x] ~~Update `nanobot/config/paths.py`: each `get_*` helper accepts optional `ctx`~~ — **deviation:** kept globals untouched; added `get_users_root()` + `get_user_root(user_id)` and put per-user resolution exclusively on `UserContext` methods. Forces every call site in Slice C to explicitly opt into per-user via `ctx.<method>()` rather than risk silent leaks from a forgotten `ctx=` kwarg. Aligns with `.agent/design.md` "Explicit over magical".
- [x] Validate `user_id` against ULID regex before path interpolation (path-traversal guard) — `UserContext.__post_init__` calls `assert_ulid`; `get_user_root` accepts only what UserContext passes.
- [ ] ~~Debug log when ctx-aware helper called with `ctx=None` during a known user-request lifecycle~~ — deferred to Slice C: contextvar + warning to be added together with first ctx-threaded call site, so the warning has actual call sites to catch leaks against. No dead code now.

**Acceptance:** Unit tests: with-ctx path resolves under `users/<uid>/`; without-ctx path identical to legacy; malformed user_id raises `ValueError`.

**Verify:** `pytest tests/config/test_paths.py -v`. Grep `Path.home() / ".nanobot"` in agent/ tools/ — all call sites traced to either ctx-aware helper or known-global path (channels, bridge).

### A5. SessionManager + WS handshake → UserContext

- [x] `nanobot/session/manager.py`: `SessionManager` accepts optional `UserContext` in constructor; history root resolved via `ctx.sessions_dir()` when present, legacy path otherwise
- [x] `nanobot/channels/websocket.py`: handshake reads `Cookie: nanobot_session=…` → calls `AuthService.verify_session()` → sets `connection.user_id`. Static-token / `?token=` path retained for non-browser clients (admin only)
- [x] On inbound message: build `UserContext(connection.user_id)` and attach to `InboundMessage.user_context` (new optional field on `InboundMessage`)
- [x] `AgentLoop`: when `msg.user_context` present, pass through to `AgentRunner` and tool registry instantiation — implemented via `_sessions_for(user_ctx)` factory cached per-user; threaded through `_dispatch`, `_process_message` (system + regular branches), `_run_agent_loop`, `_set_runtime_checkpoint`
- [ ] ~~`AgentRunner`: per-request tool registry built from `UserContext`~~ — **deferred to Slice C** (per plan: "MCP, cron, subagent, my_tool: audit but leave per-user wiring as deferred work"). For A5 acceptance, session isolation alone proves the threading; tool registry still binds to global workspace until Slice C1 rewires it.

**Acceptance:** Integration test: create user → login via HTTP → open WS with cookie → send `{type:"user",content:"hello"}` → assert file in `~/.nanobot/users/<uid>/sessions/` exists AND no new file in `~/.nanobot/sessions/`.

**Verify:** `pytest tests/auth/test_session_isolation.py -v`. Manual: log in via webui, send message, `ls ~/.nanobot/users/*/sessions/`.

### A6. WebUI login page + auth context

- [x] `webui/src/auth/AuthContext.tsx`: React context holding `{user, status: 'loading'|'authed'|'anon'}`; on mount calls `/auth/me`
- [x] `webui/src/auth/LoginPage.tsx`: email + password form, submits to `/auth/login`; on success refreshes auth context and redirects to chat
- [x] Gate main chat surface — implemented as `<AuthGate>` wrapping `<App />` in `main.tsx` (cleaner than editing App.tsx) — shows `<LoginPage />` when `status === 'anon'`, "Loading…" on `loading`
- [x] `webui/src/lib/api.ts`: new `authFetch` helper with `credentials: 'include'`; `authMe()`, `authLogin()`, `authLogout()` exported. Existing Bearer-token helpers left unchanged (orthogonal — chat WS bootstrap still uses ?token= for now).
- [ ] ~~WS client: drop manual `?token=` for browser path~~ — **deferred** to a follow-up cleanup commit. Cookie path already works on the WS handshake (A5 proved it), and the static `?token=` path is retained in parallel. Removing one without the other in a single commit risks lockout in production where token-issue-secret is configured. Will land after Slice B (signup) when cookie path is the canonical UX.
- [x] **Bonus fix:** ported `localStorage` shim from `main` into `webui/src/tests/setup.ts` — pre-existing infra gap on `nightly` that blocked any vitest run. Test suite went 0/80 → 84/84.
- [x] **Note:** `/auth/*` lives on gateway port 18790 (not the WS channel 8765, which can't parse POST bodies). Vite proxy `/auth` rewritten to `authTarget` (`NANOBOT_AUTH_URL` env or default `http://127.0.0.1:18790`).

**Acceptance:** Vitest passes for AuthContext state machine (loading→anon→authed→anon). Manual smoke: visit `localhost:5173` → see login page → log in with test user → chat surface appears → reload → still logged in.

**Verify:** `cd webui && bun run test`. `bun run build` clean. Browser manual smoke.

### ✋ Checkpoint A — Human Review

Before continuing: confirm path-resolution refactor stayed scoped to listed files; no unintended sprawl into channels or providers. Re-read `.agent/design.md` core invariants.

---

## Slice B — Multi-User: Signup + Two Users Isolated

### B1. /auth/signup route + WebUI signup page

- [x] `POST /auth/signup {email, password, display_name?}` → creates user (role='user'), mints session, returns same shape as `/auth/login`
- [x] Reject duplicate email with 409
- [x] Password policy: min 12 chars (configurable later, hardcoded for v1)
- [x] `webui/src/auth/SignupPage.tsx`: form + "have an account? log in" link
- [x] Route between login/signup via tab/button — `<AuthGate>` flips between `<LoginPage onSwitchToSignup>` and `<SignupPage onSwitchToLogin>` via local `mode` state

**Acceptance:** Integration test: signup → cookie set → GET /auth/me returns new user → repeat signup with same email returns 409.

**Verify:** `pytest tests/auth/test_routes.py::test_signup -v`. Webui vitest. Manual.

### B2. Rate limit on /auth/* endpoints

- [x] In-memory token bucket: 5 attempts / min / IP for `/auth/login`, 3 / min / IP for `/auth/signup` — `nanobot/auth/ratelimit.py:RateLimiter` (sliding window, injectable clock for tests)
- [x] On limit hit return 429 + `Retry-After` header
- [x] Audit log row on each failed attempt and each rate-limit trip — login.fail rows already written by AuthService; new `ratelimit.trip` event emitted when limit trips

**Acceptance:** Test: 6 rapid login attempts → 6th returns 429. Test: timer advances, attempts allowed again after window.

**Verify:** `pytest tests/auth/test_ratelimit.py -v`.

### B3. Logout button + auth state in WebUI

- [x] Add logout button to existing webui header / user menu — placed in `Sidebar.tsx` footer row alongside display name
- [x] On logout: clear React auth context — `AuthContext.logout()` already drops to anon; AuthGate immediately renders `<LoginPage />` again (no hard redirect needed, SPA re-renders)
- [x] Add `user.display_name` (or email) in header when authed — `displayLabel = user.display_name?.trim() || user.email`

**Acceptance:** Manual smoke: log in → see name in header → click logout → returned to login page; cookies cleared.

**Verify:** Manual browser smoke. Vitest for AuthContext logout transition.

### B4. Cross-user isolation tests

- [x] ~~Spawn gateway on ephemeral port~~ — **deviation:** drove the auth dispatcher directly (`dispatch(req, svc)`) rather than spinning a real socket. Same code path, no flaky port allocation. Live HTTP smoke through vite proxy already validates the socket layer end-to-end.
- [x] Assert alice's per-user dir disjoint from bob's — covered by `test_two_users_signup_login_no_state_overlap` and `test_concurrent_session_dirs_disjoint_on_disk`
- [x] Assert filesystem: `~/.nanobot/users/<alice>/sessions/*` disjoint from `~/.nanobot/users/<bob>/sessions/*`

**Acceptance:** Test passes deterministically.

**Verify:** `pytest tests/auth/test_isolation_multi.py -v`.

### ✋ Checkpoint B — Human Review

Confirm UX feels right (login/signup flows). Confirm test coverage credible.

---

## Slice C — Per-User Tool State + Memory + Media

### C1. Workspace tools (filesystem/shell/read/write/edit/list)

- [x] ~~Tool factory/registry in `nanobot/agent/tools/registry.py` accepts `UserContext`~~ — **deviation:** chose a `ContextVar`-based approach instead. `nanobot/auth/context.py:current_user_ctx` is set/reset by `AgentLoop._dispatch` for the duration of each request; `_FsTool` and `ExecTool` consult it dynamically to rebase `workspace`/`allowed_dir`/`working_dir` under `users/<uid>/workspace`. Avoids rebuilding the registry per request and per-user instance caching. Tools stay singletons; user routing is async-task-scoped.
- [x] Audit each tool — `filesystem.py`'s `_FsTool` base (covers ReadFile/WriteFile/EditFile/ListDir/Glob/Grep/NotebookEdit since they all extend it) and `shell.py`'s `ExecTool`. `Path.home() / ".nanobot"` is not used by request-path tools; channel/media helpers already accept ctx (Slice A4) or stay global by design.
- [ ] ~~Tool registry built **per-request**~~ — superseded by contextvar (above). No module-level caching to remove; the existing module-level tool instances are now context-aware.

**Acceptance:** Integration test — alice's filesystem write creates file under `users/<alice>/workspace/`; bob's shell ls of `~/` (when sandboxed to workspace) does not see alice's files.

**Verify:** `pytest tests/auth/test_tool_isolation.py -v`. Grep for module-level tool caches.

### C2. Memory store per-user

- [x] Memory file paths now resolved per-user — `ContextBuilder.memory` became a property that returns a per-user `MemoryStore` cached by `user_id`. The store is rooted at `ctx.workspace_path()` so memory lives at `users/<uid>/workspace/memory/` (kept inside the workspace because `GitStore` tracks files relative to the workspace root). **Deviation from plan path layout** (plan had `users/<uid>/memory/` as a sibling of workspace; that doesn't compose with GitStore — refactor to a unified layout is a follow-up).
- [ ] ~~Dream consolidation scheduler iterates user dirs~~ — **deferred**: Dream is a global cron job that operates on the loop's default workspace. Per-user dream cycles need their own scheduler design; out of scope for v1.
- [x] Atomic writes + fsync preserved per-user — `MemoryStore` internals unchanged; only its workspace root is routed via the contextvar.
- [x] `SkillsLoader` also routed per-user (was bundled with MemoryStore construction).

**Acceptance:** Test: alice writes a fact via memory tool → bob's memory recall returns empty. Dream cycle running for both users produces two separate consolidation logs.

**Verify:** `pytest tests/auth/test_memory_isolation.py -v`.

### C3. Media uploads + tool-results

- [x] WS channel media save: `_save_envelope_media` now accepts `user_ctx` and routes to `ctx.media_dir("websocket")` when present; falls back to global `get_media_dir("websocket")` for unauth/CLI paths
- [x] Tool-results dir follows per-user — `AgentRunSpec.workspace` is now derived from `current_user_ctx` at run-spec construction so `maybe_persist_tool_result(workspace, …)` writes under `users/<uid>/workspace/.nanobot/tool-results`
- [ ] ~~Media URL signing: include user_id in signed URL; verify against request cookie~~ — **deferred**: requires reshaping the HMAC payload (currently encodes a relative path under the global media root) and adding cookie verification on `/api/media/...`. Per-user uploads already land in distinct directories so cross-user fetch would need an attacker to forge a signed URL for another user's path. Hardening tracked for Slice E (security hardening).

**Acceptance:** Test: alice uploads image → file at `users/<alice>/media/...`; bob requesting `/api/media/<alice's path>` returns 403 even with valid cookie.

**Verify:** `pytest tests/auth/test_media_isolation.py -v`. Manual: paste image in webui for both users, inspect filesystem.

### C4. file_state store audit

- [x] Audited `nanobot/agent/tools/file_state.py`: `FileStateStore.for_session` keyed by `session_key` only. Two users sharing a `session_key` (e.g. unified_session or a forced override) would have **collided** — fixed.
- [x] Prefixed keys with `user_id::` when `current_user_ctx` is bound, leaving the legacy key shape intact for CLI/channel paths.

**Acceptance:** Test or code review confirms no shared mutable map across users.

**Verify:** Code review note in PR; targeted test if collision was found.

### C5. MCP / subagent / cron audit (deferred wiring OK)

- [x] Audited each remaining tool:

  | Tool | Per-user-relevant? | Status | Rationale |
  |---|---|---|---|
  | filesystem | yes | **done** (C1) | `_FsTool` consults `current_user_ctx` |
  | shell (`exec`) | yes | **done** (C1) | `ExecTool.working_dir` is a property |
  | tool-results spill | yes | **done** (C3) | `AgentRunSpec.workspace` from contextvar |
  | media uploads (WS) | yes | **done** (C3) | `_save_envelope_media(user_ctx=)` |
  | memory | yes | **done** (C2) | `ContextBuilder.memory` is a property |
  | skills loader | yes | **done** (C2) | `ContextBuilder.skills` is a property |
  | file_state | yes | **done** (C4) | key prefixed by user_id |
  | `image_generation` | yes | **deferred** | `self.workspace` is set at ctor; same property pattern would work but artifact paths flow into provider configs and signed media URLs — better landed alongside C3's signed-URL hardening |
  | `message` (send) | partial | **deferred** | uses workspace for outbound media staging only; channel-admin scope dominates |
  | `spawn` (subagent) | yes | **deferred** | subagent inherits parent loop's tools and workspace; the parent already routes per-user, so subagents inherit isolation transitively as long as they don't re-bind the contextvar before invocation |
  | `self` (MyTool) | n/a | **deferred** | self-modification is admin-only |
  | MCP servers | shared | **keep global** | MCP processes are gateway-scoped resources; per-user MCP allowlist is an explicit non-goal for v1 (plan.md Out of Scope) |
  | cron (gateway) | shared | **keep global** | per-user cron is an explicit non-goal for v1 |
- [x] Follow-ups recorded inline in this table; will be hoisted into `docs/auth.md` "Known limitations" during Slice E.

**Acceptance:** PR description includes audit table: tool / per-user-relevant? / done-or-deferred / rationale.

**Verify:** PR description complete; follow-up issues filed for deferred.

### ✋ Checkpoint C — Human Review

Confirm tool-registry refactor stayed surgical. Confirm test matrix actually covers cross-user paths (not just same-user happy path).

---

## Slice D — Admin CLI + Role + Admin Page

### D1. CLI user subcommands

- [x] `nanobot/cli/user.py`: typer sub-app with `list`, `create`, `promote`, `demote`, `reset-password`, `delete` (+ bonus `disable --on/--off`)
- [x] Registered under `nanobot user …` in `nanobot/cli/commands.py`
- [x] All commands write audit_log entries with `actor_user_id=None` (CLI = system actor) via `AuthService._audit`

**Acceptance:** Each subcommand has a unit test + a smoke test. `nanobot user list` shows all users with role, last_login, disabled flag.

**Verify:** `pytest tests/cli/test_user_commands.py -v`. Manual: run each subcommand against a fresh `auth.db`.

### D2. Role check middleware

- [x] ~~HTTP route registry tags routes as public/authed/admin~~ — **deviation:** kept the existing flat dispatch and inlined a `_require_admin(req, svc)` helper. Three lines per admin handler, no registry abstraction. Aligns with `.agent/design.md` "less structure, more intelligence".
- [x] Admin routes require `user.role == 'admin'` (and not disabled), else 401/403
- [x] `/admin/users` endpoint live; verified via curl through the vite proxy

**Acceptance:** Test: non-admin user with valid cookie → 403 on `/admin/users`. Admin user → 200.

**Verify:** `pytest tests/auth/test_role_middleware.py -v`.

### D3. /admin/users JSON endpoint

- [x] GET `/admin/users` → list users. ~~Pagination~~ deferred — v1 deployments are single-team scale; revisit when >100 users is real.
- [x] POST `/admin/users/<id>/role {role}` → promote/demote (writes `promote`/`demote` audit event)
- [x] POST `/admin/users/<id>/disabled {disabled}` → toggle; disabling also revokes active sessions
- [x] DELETE `/admin/users/<id>` → delete user + cascade sessions (foreign-key ON DELETE CASCADE). On-disk `users/<id>/` directory left in place; admin gets a CLI hint. Self-delete blocked with 400.

**Acceptance:** Integration tests for each verb. Filesystem residue documented (not auto-deleted to prevent data loss).

**Verify:** `pytest tests/auth/test_admin_routes.py -v`.

### D4. WebUI admin page

- [x] `webui/src/admin/AdminUsersPage.tsx`: table with email/display_name, role, created, last_login, disabled
- [x] Promote/demote, disable/enable, delete (confirm modal). Self-row actions are disabled in the UI to prevent operator lockout.
- [x] Admin link in the **sidebar footer** (cleaner than header alongside settings/logout), gated on `user.role === 'admin'`
- [x] Vitest covers self-row lockout, list rendering, error surfacing, promote payload, delete confirm flow. ~~"non-admin sees nothing"~~ — admin link is conditional in Sidebar (rendered only when role==='admin'); no separate vitest because the conditional is one line of code.

**Acceptance:** Manual smoke: log in as admin → see Admin link → manage another user → log in as that user → no Admin link.

**Verify:** Webui vitest + browser smoke.

### ✋ Checkpoint D — Human Review

Confirm admin UX is minimal but functional. Confirm no admin actions are exposed without role check.

---

## Slice E — Migration + Hardening + Docs

### E1. Legacy-state migration on startup

- [ ] `nanobot/auth/migration.py`: on gateway startup, check if `~/.nanobot/users/` absent AND any of `sessions/`, `workspace/`, `memory/` present
- [ ] If yes: rename `~/.nanobot/` to `~/.nanobot.legacy.<ISO-date>/`, recreate fresh `~/.nanobot/` with empty `users/`, copy over `config.json` if present
- [ ] Log loud warning with copy-paste rollback instructions (`mv ~/.nanobot.legacy.<date>/ ~/.nanobot/` if you didn't want this)
- [ ] Honor `NANOBOT_SKIP_LEGACY_MIGRATION=1` env to bypass
- [ ] `filelock` on `~/.nanobot/.migration.lock` to dodge gateway+CLI startup races

**Acceptance:** Test with temp HOME and synthetic legacy tree → migration runs, archive exists, fresh tree exists, config preserved. Second startup: no-op. With skip flag: no archive.

**Verify:** `pytest tests/auth/test_migration.py -v`.

### E2. Cookie + CSRF hardening

- [ ] Confirm `Secure` flag auto-set when gateway runs behind TLS (detect via `X-Forwarded-Proto` or explicit config)
- [ ] Implement double-submit CSRF token for `/auth/login` + `/auth/signup` + `/admin/*` state-changing routes
- [ ] Document SameSite=Lax limitations re: cross-origin

**Acceptance:** Test: state-changing request without CSRF token → 403. Same with → 200.

**Verify:** `pytest tests/auth/test_csrf.py -v`.

### E3. docs/auth.md (new)

- [ ] Operator setup: env vars, first-run UX, creating first admin
- [ ] CLI reference for `nanobot user ...`
- [ ] Threat model summary (link to plan.md if kept in tree, or inline)
- [ ] Known limitations & deferred items (no email verify, admin-only channels, etc.)

**Acceptance:** Doc renders, link checker clean, covers operator's must-know surface.

**Verify:** `markdownlint docs/auth.md` (if configured); manual read.

### E4. Update existing docs

- [ ] `docs/configuration.md`: per-user dir layout, what's global vs per-user
- [ ] `docs/deployment.md`: note multi-tenant default; first-run migration warning
- [ ] `.agent/security.md`: multi-tenant boundary notes
- [ ] `README.md`: brief mention with link to `docs/auth.md`

**Acceptance:** All four files updated; cross-links work.

**Verify:** `grep -r "single-tenant\|single-user" docs/` shows no stale claims.

### E5. CI + release

- [ ] `pyproject.toml`: `argon2-cffi` dep added
- [ ] CI workflow updated (if needed) to run new auth tests
- [ ] `ruff check nanobot/` clean
- [ ] Webui `bun run test` + `bun run build` clean
- [ ] Open PR against `nightly` with:
  - links to plan.md & this todo
  - manual smoke checklist
  - audit table for deferred per-user wiring (from C5)
  - rollback plan (mv legacy archive back)

**Acceptance:** CI green. PR opened, reviewer assigned.

**Verify:** `gh pr view` shows green checks.

### ✋ Checkpoint E — Final Review

Pre-merge: walk through every Success Criterion in plan.md. If any fail, fix before merge.

---

## Working Notes

- Branch off `nightly` per CONTRIBUTING.md, not `main`.
- Keep `loop.py` / `runner.py` diffs minimal per `.agent/design.md`. If a slice's loop diff grows past ~30 lines, stop and re-design — likely belongs in a helper / tool registry layer.
- Per `.agent/design.md` "Explicit over magical": every path resolution must trace from a `UserContext` (or be intentionally global). No silent "default to global" fallbacks inside user-request code.
- Update this todo as you go (`[~]` while in progress, `[x]` when done).
