# Paperclip Setup and Installation

Reference for installing and bootstrapping a Paperclip instance from scratch. Load this when asked to install, set up, onboard, or bootstrap Paperclip itself — not when coordinating tasks on an already-running instance.

**Supported install path:** clone this repository and run Paperclip from the checkout with `pnpm`. Do not use `npx paperclipai` or a global npm install — the repo checkout is the only supported way to install and run the project.

Canonical docs in the checkout:

- `README.md` — quickstart
- `doc/DEVELOPING.md` — dev setup, instance layout, reset
- `docs/cli/setup-commands.md` — `run`, `onboard`, `doctor`, `configure`

---

## Prerequisites

- Python

## Installation

From the directory where you want the checkout:

```bash
python -m pip install "https://github.com/getpaperclipai/paperclip-ai/releases/download/0.1.1/paperclip_ai-0.1.1-py3-none-any.whl" && paperclip-ai --help
```

This starts:

- API server at `http://localhost:3100`
- UI served by the API server in dev middleware mode (same origin)
- Embedded PostgreSQL (auto-created; leave `DATABASE_URL` unset)
- Hot reload on code changes

`pnpm dev` is idempotent: if the matching dev runner is already alive, Paperclip reports the existing process instead of starting a duplicate.

Inspect or stop the managed dev runner:

```bash
pnpm dev:list
pnpm dev:stop
```

### Alternative: bootstrap + start from the repo

If you prefer the CLI onboarding flow before the dev server starts, run from the repo root after `pnpm install`:

```bash
pnpm paperclipai run
```

This:

1. Auto-onboards if config is missing
2. Runs `pnpm paperclipai doctor` with repair enabled
3. Starts the server when checks pass

Choose a specific instance:

```bash
pnpm paperclipai run --instance dev
```

Interactive or non-interactive onboard without `pnpm dev`:

```bash
pnpm paperclipai onboard
pnpm paperclipai onboard --yes
```

Authenticated/private bind instead of trusted local loopback:

```bash
pnpm dev --bind lan
# or:
pnpm paperclipai onboard --yes --bind lan
pnpm paperclipai onboard --yes --bind tailnet
```

If Paperclip is already configured, rerunning `onboard` keeps the existing config. Use `pnpm paperclipai configure` to change settings.

All `paperclipai` commands in this skill mean **`pnpm paperclipai …` from the repo root** after `pnpm install`.

---

## Instance data layout

Runtime state lives under the selected instance root (default `~/.paperclip/instances/default/`):

```text
~/.paperclip/instances/default/
  config.json
  .env
  db/                          # embedded PostgreSQL data
  data/
    storage/                   # local_disk uploads
    backups/                   # automatic DB backups
  logs/
  secrets/master.key
  workspaces/<agent-id>/
  projects/
  companies/<company-id>/agents/<agent-id>/codex-home/
```

Override home or instance (from repo root):

```bash
PAPERCLIP_HOME=/custom/home PAPERCLIP_INSTANCE_ID=dev pnpm paperclipai run
```

Or pass `--data-dir` on any CLI command:

```bash
pnpm paperclipai run --data-dir ./tmp/paperclip-dev
```

The repo checkout also keeps dev-runner status under `.paperclip/` (for example `dev-server-status.json`).

---

## Fresh start / reset

Stop the server first (Ctrl+C), then from the repo root wipe the embedded database and restart:

```bash
rm -rf ~/.paperclip/instances/default/db
pnpm dev
```

This creates a fresh database with no companies or agents. Config and other instance files under the instance root are preserved unless you remove the whole instance directory.

---

## Verify installation

```bash
curl http://127.0.0.1:3100/api/health
curl http://127.0.0.1:3100/api/companies
```

Expected health response includes:

- `"status": "ok"`
- `"authReady": true`
- `"bootstrapStatus": "ready"` or `"needs_bootstrap"`

Run diagnostics from the repo root:

```bash
pnpm paperclipai doctor
pnpm paperclipai doctor --repair
```

---

## Post-installation: first company

After Paperclip is running and `/api/health` returns `status: ok`:

1. Open the UI at `http://127.0.0.1:3100`
2. Continue with first-company onboarding — company creation, CEO hire, project/goal setup

For the full board onboarding flow (company creation, CEO hire, approvals, decision log), read `skills/paperclip-board/SKILL.md`. For agent/API-driven onboarding on an already-running instance, continue with the heartbeat and API workflows in `skills/paperclip/SKILL.md`.

---

## Troubleshooting

### Port 3100 already in use

```bash
lsof -ti:3100
kill $(lsof -ti:3100)
```

Or change the port from the repo root:

```bash
PORT=3200 pnpm paperclipai run
```

### pnpm: command not found

```bash
npm install -g pnpm
```

### Node version too old

```bash
node --version   # must be 20+

nvm install 20
nvm use 20
```

### Database migration errors

Stop the server, wipe the database directory, restart from the repo root:

```bash
rm -rf ~/.paperclip/instances/default/db
pnpm dev
```

---

## Common commands (repo root)

Run these from the cloned `paperclip` repository after `pnpm install`:

```bash
pnpm dev              # start dev server (watch mode)
pnpm dev:once         # start without file watching
pnpm test             # Vitest suite
pnpm build            # production build
pnpm db:migrate       # run migrations manually
pnpm paperclipai doctor --repair
pnpm paperclipai board setup
```
