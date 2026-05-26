---
title: "P5: Two-way sync & hot reload"
tags: [sketch]
created: 2026-05-25
status: speculative
parent: "[[git-backed-agent-fleet]]"
prev: "[[p4-self-hosted-git-encryption]]"
---

# P5: Two-way sync & hot reload

Up to this point, sync is one-way: bot writes, human reviews via PR.
P5 closes the loop — the agent pulls upstream changes and hot-reloads.

Marked **speculative**: status above is `speculative`, not `draft`.
Resist building this until P1–P4 have proven the model.

## Scope

- Periodic `git pull` on the host (or webhook-driven).
- File watcher detects relevant changes (`IDENTITY.md`, `SOUL.md`,
  skills).
- In-process reload: `ContextBuilder` re-reads bootstrap files;
  `SkillsLoader` re-scans `skills/`. No restart needed for non-code
  changes.
- For changes that *do* require a restart (config.json, dependencies),
  signal systemd to restart.

## Mechanism

```
GitHub/Gitea ──webhook──▶ small HTTP listener on host
                                │
                                ▼
                          git fetch + reset
                                │
                                ▼
                       inotify on workspace/
                                │
                                ▼
                  nanobot reload hook (SIGUSR1?)
```

Or simpler: cron pull every N minutes. Less elegant, no webhook
infrastructure, more than enough.

## Hard parts

### Conflict resolution

The bot is committing locally; the human pushes to main. When the host
pulls, the bot's local commits diverge from the remote. Options:

| Strategy | Behavior | Risk |
|----------|----------|------|
| Rebase local onto remote | Bot's edits preserved on top | Memory consolidation race; complex with encrypted files |
| Reset hard to remote | Human wins; bot loses any unpushed local work | Memory loss if push fails |
| Merge | Standard git merge | Conflicts in MEMORY.md will halt the pull |

Most safe: the bot pushes to its host branch *frequently*, never
holds unpushed state for long, and the pull only ever fast-forwards
the agent's host branch. `main` changes propagate via a separate
"identity update" path. Read-only branches per agent role.

### Mid-turn reload

If `IDENTITY.md` changes while the LLM is mid-tool-call, swapping
context mid-flight is hazardous. Mitigations:

- Defer reload until the current turn completes.
- Use a generation counter — new turns get the new identity, in-flight
  turns finish under the old.
- The session manager already keys by `channel:chat_id`; a reload bumps
  a `context_version` that's compared at turn start.

### Skills changing

Skills are loaded once at startup. Reload requires invalidating the
loader's cache. Manageable, just plumbing.

## Decisions

| # | Question | Default |
|---|----------|---------|
| 1 | Pull cadence | Webhook-driven; cron every 5 min as fallback. |
| 2 | Reload scope | IDENTITY/SOUL/USER/skills → hot. Config → restart. |
| 3 | Conflict policy | Bot always rebases onto remote on its host branch. Identity changes via PR-merged main only. |
| 4 | Mid-turn behavior | Defer reload; new turns get new context. |
| 5 | Notification of reload | Log line + optional "identity refreshed" message via [[fs-mailbox]] to user? |

## Concerns

- **Complexity-to-value ratio is questionable.** P1–P4 cover most of
  the GitOps benefits. Two-way sync is a real-time loop with
  failure modes most projects regret.
- **Encrypted files complicate everything.** Decrypt before reload;
  re-encrypt before any bot-driven write. Filter pipeline must run on
  every pull/push.
- **State machine.** New transitions: clean / pulling / reloading /
  conflict / quarantine. Debug surface grows.
- **Trust.** Webhook listener accepting reload signals on the public
  internet needs hardening (signed payloads, allowlist).

## Open questions

- Is there a real use case that P1–P4 doesn't cover? Examples:
  - Editing IDENTITY.md from a phone and having Peewee adopt the new
    persona without SSH.
  - Coordinating identity changes across replicas.
- Should reload be opt-in per file? Probably — `.nanobot-reload`
  manifest listing files that trigger hot reload.
- Webhook framework vs raw HTTP? Anything beyond a single endpoint is
  overkill.

## When to actually do this

Only if all are true:
1. P1–P4 are stable and we've lived with them for ≥1 month.
2. Manually pushing identity changes is genuinely friction.
3. We accept the operational complexity.

Otherwise: leave as `speculative`. The vault is a fine place for ideas
that may never ship.

## Related

- [[git-backed-agent-fleet]] — parent overview
- [[p4-self-hosted-git-encryption]] — preceding phase
- [[memory-consolidation]] — primary write path that must remain race-free
