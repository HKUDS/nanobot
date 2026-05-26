---
title: "P4: Self-hosted git & at-rest encryption"
tags: [sketch]
created: 2026-05-25
status: draft
parent: "[[git-backed-agent-fleet]]"
prev: "[[p3-multi-agent-fleet]]"
next: "[[p5-two-way-sync]]"
---

# P4: Self-hosted git & at-rest encryption

By the end of [[p3-multi-agent-fleet]], we have a working fleet pushing
to GitHub. MEMORY.md will contain personal information about humans the
agents interact with. P4 closes the obvious leak.

Two independent moves, either valuable alone:

- **Self-hosted git**: workspace repos move off GitHub onto a Gitea
  instance on the same droplet (or another we control).
- **At-rest encryption**: sensitive workspace files become opaque blobs
  in the repo. Plaintext only on the live host.

## Scope

- Gitea (or Forgejo) deployed via docker-compose, managed by terraform.
- Workspace repos migrated from GitHub.
- `age` or `sops` encrypts MEMORY/HISTORY before commit; decrypts on
  pull.
- Existing tooling (clone, diff, log) still works for non-encrypted
  files (IDENTITY/SOUL/skills).

## Self-hosted git: Gitea

```hcl
module "gitea" {
  source = "./modules/gitea"
  host_id = digitalocean_droplet.sphelps_net.id
  domain  = "git.sphelps.net"
  data_dir = "/var/lib/gitea"
  admin_user  = "sphelps"
  admin_email = var.admin_email
}
```

Backups: nightly `tar` of `data_dir` to DO Spaces. The git history *is*
the agent's biography — losing it loses years of memory consolidation.

## At-rest encryption: candidates

| Tool | Strengths | Weaknesses |
|------|-----------|-----------|
| `age` | Simple, modern, key files | No first-class git integration; we'd write the hooks ourselves |
| `sops` | Used widely in IaC; metadata preserved | Designed for structured data, awkward for markdown |
| `git-crypt` | Transparent; works via gitattributes | Symmetric keys; harder to rotate |

Leaning **age** with custom clean/smudge filters: encrypt `MEMORY.md`
on commit, decrypt on checkout. Keys distributed via the same TF
flow that writes config.json.

```
# .gitattributes
workspace/MEMORY.md   filter=age diff=age
workspace/HISTORY.md  filter=age diff=age
```

Plaintext stays in the live working tree; what's in `.git/objects` is
encrypted.

## Decisions

| # | Question | Default |
|---|----------|---------|
| 1 | Move off GitHub entirely or keep public repos for non-sensitive parts? | Move agent repos. Keep nanobot fork on GitHub (it's already public). |
| 2 | Per-file or whole-repo encryption? | Per-file via `.gitattributes`. Keeps IDENTITY/skills diffable. |
| 3 | Key per agent or one fleet key? | Per agent. Smaller blast radius if one leaks. |
| 4 | Where do keys live? | Encrypted in TF state. Written to host on apply. Never in repo. |
| 5 | Rotate keys how? | Re-encrypt + commit. Annual? On significant secret event? Decide later. |

## Concerns

- **Opaque diffs.** Once MEMORY.md is encrypted, `git log -p` no longer
  shows what changed. Mitigate with a local "decrypted clone" workflow:
  pull, decrypt, inspect, re-encrypt. Tooling needed.
- **Key loss = data loss.** Multiple key custodians (yubikey + 1Password
  + paper backup). Test recovery quarterly.
- **Searchability lost.** `git grep MEMORY.md` returns nothing useful.
  Searchable encryption is hard; accept the loss in P4.
- **Performance.** age is fast (~ms per MB). Negligible for our sizes.
- **Migration window.** Moving from GitHub means a one-shot script
  that rewrites history with encrypted blobs. Or accept a fresh start:
  archive the GitHub repo, init a new encrypted repo from current
  state. Simpler — recommend.
- **Gitea uptime.** Self-hosting means single-host availability.
  Workspace operations gracefully degrade if Gitea is down: commit
  locally, push later.

## Open questions

- Replace Gitea with Forgejo (community fork) for license alignment?
  Probably yes; ops are identical.
- Do we encrypt skills too? Probably not — they're code.
- Re-encryption pipeline if a key is compromised: how is it triggered?
- Backup encryption: encrypt the Gitea backup too? Yes; doesn't move
  the trust boundary.

## Done when

- Gitea is reachable from the host(s) running the agents.
- Agent repos are mirrored to Gitea and GitHub copies archived.
- A commit to MEMORY.md stores an encrypted blob in Gitea.
- A fresh clone + decrypt produces the working plaintext.
- Backup restore on a clean Gitea instance works.

## Related

- [[git-backed-agent-fleet]] — parent overview
- [[p3-multi-agent-fleet]] — preceding phase
- [[p5-two-way-sync]] — next phase
