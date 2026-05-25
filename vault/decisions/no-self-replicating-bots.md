---
title: "Bots cannot create, destroy, or modify infrastructure"
tags: [decision]
created: 2026-05-25
status: accepted
---

# Bots cannot create, destroy, or modify infrastructure

## The rule

A nanobot agent can update its **own** workspace files. It cannot:

- Provision a new agent (no `gh repo create`, no peer onboarding)
- Delete or archive an agent
- Rotate its own or another agent's SSH/deploy keys
- Modify another agent's workspace
- Modify its own `config.json` or `IDENTITY.md`/`SOUL.md` (already enforced
  via `_PROTECTED_FILES` in `loop.py`)
- Add new tools, skills, or channels to itself
- Acquire new auth credentials (API keys, gh tokens, OAuth)

## Why

The "sorcerer's apprentice" failure mode: a confused or prompt-injected bot
that can create more bots can also create a runaway, a leaked secret on a
new repo, or a budget overrun overnight. The blast radius of any one
bot misbehaving must stay bounded by *that bot's* current resources.

Even with a registry intermediary, the dangerous primitive is "bot can
make bot". The fix isn't an intermediary — it's keeping the primitive
out of bots' hands entirely.

## How it's enforced

1. **CLI is the floor.** All infrastructure-mutating operations live in
   `nanobot fleet ...` subcommands. Invoking them requires a human shell.
2. **Tool-level channel gating.** Where we *do* expose dangerous tools to
   an LLM (e.g. the [[registry-skill]]), each tool declares
   `privileged_channels`. The agent loop refuses to invoke the tool if
   the current inbound channel isn't on the list. fs (peer-to-peer) is
   never on the list.
3. **Token segregation.** Each agent's workspace only carries the
   credentials *that agent* needs. A non-registry agent has no `gh`
   token; even if its LLM tries to call `gh repo create` via the shell
   tool, `gh` errors out with auth missing.
4. **Read-only by default.** When a bot *does* need fleet visibility
   (e.g. a librarian skill answering "what agents do we have?"), it gets
   read-only tools. Listing ≠ mutating.

## What is allowed

- Bot writes to its own MEMORY.md, HISTORY.md.
- Bot commits + pushes its own workspace via [[git-backed-agent-fleet]]
  sync (writes to *its* repo only).
- Bot reads REGISTRY.md (visibility ≠ control).
- Bot reads other agents' published IDENTITY.md / SKILL.md.

## What if we want self-organization later?

The principle is "no infra mutation by bots", not "bots can't coordinate".
Coordination via mailbox (proposing, asking, recording) is fine. Anything
that would result in a new repo, new key, or new spend goes through the
CLI by a human.

If we ever revisit, the alternative model would be:

- A "proposal" mailbox where bots can suggest changes (new agent, key
  rotation, etc.).
- A human review queue that runs the CLI on approval.

That preserves bot expressiveness without ceding the primitive.

## Related

- [[git-backed-agent-fleet]]
- [[agent-fleet-cli]]
- [[registry-skill]] — channel-gated convenience layer
