# Claude Code — Developer Guide

You are running inside a **cc-dev-** container on a remote Docker host. This file describes your environment, workflow, and conventions.

---

## Environment

| Item | Value |
|------|-------|
| Workspace | `/home/claude/workspace` — fork of `https://github.com/HKUDS/nanobot.git` |
| Fork | `pve/nanobot-ai` |
| Registry | `ghcr.io/pve/nanobot-ai` |
| Scripts | `/opt/cc/scripts/` — baked into this image |
| AI backend | OpenRouter — `OPENROUTER_API_KEY` env var is set |

You are in **dev**. You do not have access to acceptance or production environments.

---

## How code reaches production

```
/workspace  ──git push──▶  pve/nanobot-ai  ──PR merge──▶  /opt/cc/scripts/package.sh
                                                                      │
                                                              ghcr.io registry
                                                                      │
                                                     ┌────────────────┴──────────────────┐
                                                     ▼                                   ▼
                                              acceptance (cc-acc)                 production (cc-prod)
                                              observe only                        observe only
```

User manually approves each promotion gate. You do not promote builds yourself.

---

## Scripts at /opt/cc/scripts/

| Script | When to use |
|--------|-------------|
| `/opt/cc/scripts/setup-dev.sh` | One-time init — already run during container setup |
| `/opt/cc/scripts/package.sh [tag]` | After tests pass — builds and pushes image to registry |
| `/opt/cc/scripts/spawn-dev.sh <name>` | To create a parallel dev instance for a separate branch |
| `/opt/cc/scripts/ls-dev.sh` | To see all running dev instances and their SSH ports |

---

## Git and PR conventions

- **Never commit directly to `main`** — always work on a feature branch
- Keep `main` current: `git fetch upstream && git merge --ff-only upstream/main`
- Commit style: conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`)
- Open PRs with `gh pr create` — target branch: `main` on `pve/nanobot-ai`
- **Never merge your own PRs** — user approval is required at every gate

---

## Constraints

- Do not push to the upstream repo directly — PRs to your fork only
- Do not merge your own PRs
- Do not attempt to reach or modify acceptance or production
- Do not commit secrets or tokens
