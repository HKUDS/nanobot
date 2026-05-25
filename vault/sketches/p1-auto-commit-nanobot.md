---
title: "P1: Auto-commit & push from nanobot"
tags: [sketch]
created: 2026-05-25
status: draft
parent: "[[git-backed-agent-fleet]]"
next: "[[p2-terraform-single-agent]]"
---

# P1: Auto-commit & push from nanobot

The minimum useful slice of [[git-backed-agent-fleet]]: nanobot itself
records workspace state to git on semantic moments. No terraform, no
multi-host. Manual repo setup; manual host deploys.

Stop here and you already get: a git diary of how the agent thinks over
time, free disaster recovery, and the ability to roll back bad memory
consolidations.

## Scope

- Track `IDENTITY.md`, `SOUL.md`, `USER.md`, `HEARTBEAT.md`, `AGENTS.md`,
  `TOOLS.md` (workspace root), `memory/MEMORY.md`, `skills/`,
  `cron/jobs.json`. Gitignore `media/`, `gateway.log`, `whatsapp-auth/`,
  and (by default) `memory/HISTORY.md`.
- Commit on semantic triggers (not every turn).
- Push to a per-host branch.
- Stay out of `main` — humans curate that via PR.

> Implementation uses `git add -A` and trusts the workspace `.gitignore`.
> A recommended `.gitignore` ships in the agent repo template
> (see [[p2-terraform-single-agent]] when that lands).

## New module: `nanobot/sync/git.py`

A thin wrapper. Plumbing only — no creative behavior.

```python
class WorkspaceSync:
    def __init__(self, workspace: Path, config: SyncConfig): ...
    async def commit(self, reason: str, files: list[Path] | None = None) -> None
    async def push(self) -> None
    async def shutdown(self) -> None  # commit-on-exit hook
```

Uses `subprocess` against the system `git`. No GitPython dep — that
library has historically been a memory hog and we already shell out for
other tools.

## Config shape

```python
class SyncConfig(Base):
    enabled: bool = False
    remote: str = ""              # e.g. "git@github.com:phelps-sg/agent-peewee"
    branch: str = ""              # default: host/<hostname>
    push: bool = True
    track_history: bool = False   # default off — HISTORY.md churns hard
    commit_on_memory: bool = True
    commit_on_shutdown: bool = True
    commit_on_heartbeat: bool = False
    max_commits_per_hour: int = 6 # throttle for runaway protection
    author_name: str = "nanobot"
    author_email: str = "nanobot@localhost"
```

Lives at `agents.defaults.sync` in `~/.nanobot/config.json`.

## Where the hooks fire

| Trigger | Site | Files captured |
|---------|------|----------------|
| Memory consolidation | `loop.py:_consolidate_memory` after success | All tracked changes (`memory/MEMORY.md` + anything else dirty) |
| Heartbeat tick (optional) | `heartbeat/service.py` end of phase 2 | All tracked changes |
| Shutdown | gateway `finally` block | All tracked changes |

Every trigger calls `WorkspaceSync.commit(reason=...)`. The throttle
silently drops commits over the per-hour budget — the next trigger
collapses pending changes into one commit.

## Decisions

| # | Question | Default |
|---|----------|---------|
| 1 | Commit author = bot or human? | Bot. `author_name="nanobot"`, distinct from human commits. |
| 2 | Commit messages templated or LLM-authored? | Templated. `memory: consolidate after telegram:8775031757` — predictable, scopable, no token cost. |
| 3 | Push to `main` or per-host branch? | Per-host: `host/<hostname>`. `main` is for human-curated state. |
| 4 | Signed commits (GPG)? | No initially. Adds key-mgmt overhead. Revisit if main repo enforces it. |
| 5 | Track `HISTORY.md`? | Off by default. Append-only file with high churn — bloats git. |

## Safety

- `_PROTECTED_FILES` in `loop.py` already prevents the LLM from editing
  `IDENTITY.md`/`SOUL.md`/etc. via file tools. Re-audit before granting
  push — confirm there's no path where a poisoned message becomes a
  signed git commit on `main`.
- The throttle (`max_commits_per_hour`) caps damage from runaway
  consolidation loops.
- Push only to a host branch; never to `main` automatically.
- If push fails (auth, conflict), log loudly and continue — commits
  accumulate locally and the next push attempt drains them.

## Open questions

- HISTORY.md retention: skip, size-cap and rotate, or push to a separate
  repo (`agent-peewee-history`)? Probably skip in P1, revisit in P4.
- Heartbeat-time commits — useful, or noisy? Easy to enable later.
- One repo per agent vs monorepo of all agents. See decision in
  [[git-backed-agent-fleet]] (default: per-agent). Reconfirm in P3.
- SSH key provisioning: deploy key per host? Same key reused across
  hosts? Likely a per-host deploy key, written by [[p2-terraform-single-agent]].

## Done when

- Memory consolidation produces a commit + push within seconds.
- Bot shutdown commits any pending changes.
- Throttle works under synthetic load (loop 20 consolidations).
- `git log -p workspace/MEMORY.md` on the remote shows a clean evolution.
- Failure modes (no network, bad creds, push rejected) don't crash the
  gateway.

## Related

- [[git-backed-agent-fleet]] — parent overview
- [[memory-consolidation]] — primary commit trigger
- [[p2-terraform-single-agent]] — next phase
