---
title: Agent fleet CLI
tags: [sketch]
created: 2026-05-25
status: draft
parent: "[[git-backed-agent-fleet]]"
---

# Agent fleet CLI

CLI-driven management of the agent fleet — repos, deploy keys, registry
records. Replaces the earlier "registry bot" idea: per
[[no-self-replicating-bots]], infrastructure mutation stays out of bots'
hands.

A conversational layer (the [[registry-skill]]) sits on top of this CLI
and exposes a *subset* of operations to an agent's LLM — gated to
trusted channels.

## Commands

```bash
nanobot fleet new <name>           # create repo + keypair + deploy key
nanobot fleet list                 # show registered agents
nanobot fleet archive <name>       # gh repo archive + mark in REGISTRY
nanobot fleet rotate-key <name>    # new keypair, swap on GitHub
nanobot fleet init <name>          # bootstrap workspace on current host
```

### `fleet new <name>`

1. `gh repo create <org>/agent-<name> --private` (org configurable).
2. `ssh-keygen -t ed25519 -N "" -C "<name>@nanobot"` →
   `~/.nanobot/fleet/keys/<name>/{id,id.pub}`.
3. `gh api repos/<org>/agent-<name>/keys` → register pubkey as deploy
   key with **write** access, title `nanobot:<name>`.
4. Append a row to REGISTRY.md.
5. Print the config snippet for the new agent's host (remote URL,
   `GIT_SSH_COMMAND` line, peer ID).

### `fleet list`

Reads REGISTRY.md, prints a table.

### `fleet archive <name>`

1. `gh repo archive <org>/agent-<name>`.
2. Mark row as `archived` in REGISTRY.md.
3. Do NOT delete the keypair locally; leave it for forensics. Print
   a `gh repo unarchive` reminder.

### `fleet rotate-key <name>`

1. ssh-keygen → new keypair under `keys/<name>.next/`.
2. `gh api` add the new pubkey.
3. Tell the human to swap `GIT_SSH_COMMAND` on the host (we can't
   reach into a different host).
4. After human confirms, `gh api` remove the old key, move
   `keys/<name>.next/` → `keys/<name>/`.

### `fleet init <name>`

Run on the new agent's host. Uses REGISTRY.md to find the agent's
repo + key path. Workspace must already exist.

1. `git init -b main` in the workspace if not already a repo.
2. Drop a recommended `.gitignore` (template in `nanobot/fleet/templates.py`).
3. Add `origin` pointing at the repo from REGISTRY.
4. Configure `GIT_SSH_COMMAND` for sync via SyncConfig (or env file).
5. `git add -A && git commit -m "init: <name> snapshot" && git push`.

## REGISTRY.md format

Plain markdown so a human can edit by hand if needed. Parser tolerates
extra columns, sections, and freeform text after the table.

```markdown
# Agent Fleet Registry

| Name | Repo | Host | Created | Status | Description |
|------|------|------|---------|--------|-------------|
| peewee | phelps-sg/agent-peewee | sphelps.net | 2026-05-22 | active | Family assistant |
| iroh | phelps-sg/agent-iroh | sphelps.net | 2026-05-22 | active | Glyn's assistant |

## Notes

(free-form human notes here — not parsed)
```

Parser pulls the first markdown table and treats columns Name/Repo/
Host/Created/Status/Description as canonical. Additional columns are
preserved on write.

## File layout

```
~/.nanobot/fleet/
├── REGISTRY.md                 # source of truth
└── keys/
    ├── peewee/
    │   ├── id            (chmod 600)
    │   └── id.pub
    └── iroh/
        ├── id
        └── id.pub
```

The whole `~/.nanobot/fleet/` directory is its own git repo (optional —
operator can `git init` + push to a `phelps-sg/agent-fleet` repo for
team visibility). The CLI doesn't auto-create that repo; it just writes
locally.

## Auth

`gh` must be authenticated on the host running the CLI with scopes:

- `repo` (create / archive private repos)
- `admin:public_key` (manage deploy keys)

The CLI fails loudly if `gh auth status` shows missing scopes.

## Open questions

- Should `fleet new` auto-run `fleet init` on the same host? Probably
  yes if `--workspace` is given; otherwise just print the snippet so
  the human can run `fleet init` on the actual target host.
- Org default — hard-coded `phelps-sg` for now, or config? Defer: config
  field on `SyncConfig` or a separate `FleetConfig`.
- Backup of `keys/`. These are deploy keys — losing them means losing
  the bot's push access. Backup is user's responsibility (1Password,
  encrypted USB, etc.).

## Done when

- All five commands work end-to-end against a real GitHub org.
- A fresh agent can be brought up with `fleet new` + `fleet init` and
  immediately push from the gateway sync feature.
- REGISTRY.md is a clean source of truth post-bootstrap.

## Related

- [[no-self-replicating-bots]] — the principle this implements
- [[git-backed-agent-fleet]] — parent overview
- [[p1-auto-commit-nanobot]] — what consumes the deploy key
- [[registry-skill]] — conversational layer on top of this CLI
