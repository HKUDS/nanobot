---
title: Git-Backed Agent Fleet
tags: [sketch]
created: 2026-05-25
status: draft
---

# Git-Backed Agent Fleet

A proposal for treating nanobot agents as files-in-git, deployed via terraform.
Motivation rests on the [[agents-are-files]] thesis: if the agent is the
workspace, then `git`, `terraform`, and `cp` cover most of what a "platform"
needs to do.

## Three layers, decoupled

### 1. Agent repo (one per agent)

Example: `phelps-sg/agent-peewee`

```
peewee/
├── workspace/
│   ├── IDENTITY.md       ✓ tracked
│   ├── SOUL.md           ✓ tracked
│   ├── MEMORY.md         ✓ tracked  (the interesting churn)
│   ├── HEARTBEAT.md      ✓ tracked
│   ├── USER.md           ✓ tracked
│   ├── skills/           ✓ tracked
│   ├── cron/jobs.json    ✓ tracked
│   ├── HISTORY.md        ⚠  optional / size-capped
│   ├── media/            ✗ gitignored
│   └── whatsapp-auth/    ✗ gitignored
└── README.md
```

Config and secrets live outside the agent repo — terraform writes them at
deploy time.

### 2. Auto-commit machinery inside nanobot

A new module, e.g. `nanobot/sync/git.py`, that:

- Watches the workspace and commits on a trigger (see Decision 1).
- Pushes to a per-host branch (`host/<hostname>`); `main` is curated via PR.
- Writes commit messages with semantic context, e.g.
  `memory: consolidate after telegram:8775031757`.

### 3. Terraform registry (one repo)

Example: `phelps-sg/agent-fleet`

```hcl
resource "nanobot_agent" "peewee" {
  source_repo = "phelps-sg/agent-peewee"
  source_ref  = "main"
  host        = digitalocean_droplet.sphelps_net.id
  config_path = "~/.nanobot/config.json"
  model       = "anthropic/claude-sonnet-4-6"
  channels    = { telegram = var.peewee_telegram, fs = local.fs_peewee }
  peers       = [nanobot_agent.iroh.peer_id]
}
```

`terraform apply` SSHs the host, clones the workspace repo, writes
`config.json` from variables (with secrets), restarts the systemd unit. State
in DO Spaces or a local backend.

## The decisions that shape everything

| # | Decision | Default to argue for |
|---|----------|----------------------|
| 1 | **Commit cadence** | On memory consolidation + on SIGTERM. Captures semantic moments, doesn't churn. |
| 2 | **Repo per agent vs monorepo** | Per agent — privacy, ACL per persona, clean separation. Monorepo only if managing >5. |
| 3 | **Push branch strategy** | Bot pushes to `host/<hostname>`. Promotion to `main` via PR. Prevents bot bugs polluting canonical state. |
| 4 | **Secrets handling** | Out-of-band: terraform vars → SSH-write config.json. Nothing sensitive in the agent repo. |
| 5 | **Sync direction** | One-way (bot → git → human review). Two-way later, once we trust the loop. |

## What this unlocks

- **MEMORY.md commits become an audit log of how the agent thinks over time.**
  `git log -p workspace/MEMORY.md` is the bot's diary.
- **Disaster recovery.** Droplet dies → `terraform apply` → agent restored
  with current memories.
- **Multi-environment.** Spin up `peewee-staging` from the same repo for
  testing, without touching prod's MEMORY.
- **Identity portability.** Move hosts by changing one terraform variable.
- **Provenance for bad behavior.** "Why did the bot say X?" →
  `git blame workspace/IDENTITY.md`.

## Honest concerns

- **Privacy.** Private GitHub repos are still GitHub's. MEMORY.md will
  contain personal info. If that matters: self-hosted Gitea on the droplet,
  or age/sops at-rest encryption on the markdown (uglier diffs, cryptographic
  privacy).
- **Commit storm.** Memory consolidation might fire ~10×/day; multiply by
  agents; multiply by the LLM occasionally writing odd commit messages. Need
  a guard / max-per-hour throttle.
- **Bot-induced commits to its own identity.** Nanobot already guards
  IDENTITY/SOUL writes in `loop.py` (`_PROTECTED_FILES`). Re-audit before
  granting push.
- **Two-way sync is a tar pit.** Resist until genuinely needed. One-way
  (bot writes, human reviews via PR) covers ~90% of the value.

## Suggested phasing

| Phase | Scope | Where you can stop |
|-------|-------|--------------------|
| **P1** | Auto-commit + push in nanobot. Manual repo setup. Manual deploy. | Already valuable — git history of agent evolution. |
| **P2** | Terraform module for a single droplet, single agent. Writes config from vars. | Reproducible deploy of one agent. |
| **P3** | Multi-agent fleet, fs peer wiring driven by terraform locals. | Declarative multi-agent infra. |
| **P4** | Self-hosted git (Gitea) on the droplet, optional age/sops encryption. | Privacy-tight. |
| **P5** | Two-way sync, hot reload of IDENTITY changes. | Real GitOps loop. |

P1 alone is probably a few evenings' work and would teach us a lot.

## Open questions

- Where does the [[fs-mailbox]] live in this model — inside an agent's
  workspace, or in a separate "shared" repo that all agents pull?
- Cron jobs and skills currently live in the workspace. Treat them as code
  (PR-reviewed) or as state (bot-written)? Probably code.
- If the bot ever pushes its own commit message, do we let an LLM author it
  freely, or template it strictly? Templates are safer.
- Backup story for HISTORY.md — exclude from git but rsync to object storage?

## Related

- [[agents-are-files]] — the underlying premise.
- [[fs-mailbox]] — the inter-bot mailbox we already shipped; consider how it
  interacts with workspace sync.
- [[memory-consolidation]] — current trigger for the most interesting writes.
