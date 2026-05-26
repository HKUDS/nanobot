---
title: "P2: Terraform module for a single agent"
tags: [sketch]
created: 2026-05-25
status: draft
parent: "[[git-backed-agent-fleet]]"
prev: "[[p1-auto-commit-nanobot]]"
next: "[[p3-multi-agent-fleet]]"
---

# P2: Terraform module for a single agent

Reproducible deploy of one agent to one host. Builds on [[p1-auto-commit-nanobot]]:
the agent's workspace repo already exists and is push-able by the bot.

Stop here and you have: `terraform apply` → working bot on a fresh
droplet, no manual SSH. Disaster recovery is a single command.

## Scope

- One DigitalOcean droplet (initially sphelps.net or a clone).
- One nanobot agent (Peewee).
- All secrets injected from terraform variables → `config.json`.
- systemd unit managed by terraform.
- State in DO Spaces (S3-compatible) backend.

## Resources

```hcl
module "agent_peewee" {
  source = "./modules/nanobot-agent"

  name              = "peewee"
  host_id           = digitalocean_droplet.sphelps_net.id
  host_user         = "sphelps"
  workspace_repo    = "git@github.com:phelps-sg/agent-peewee.git"
  workspace_ref     = "main"
  deploy_key_path   = var.peewee_deploy_key

  config = {
    model        = "anthropic/claude-sonnet-4-6"
    anthropic_key = var.anthropic_api_key  # sensitive
    telegram     = { token = var.telegram_token, allow_from = [var.steve_id] }
  }
}
```

## What the module does

1. Renders `config.json` from the `config` map (template_file).
2. Writes deploy key for the workspace repo to the host.
3. `git clone` the workspace repo to `/home/sphelps/.nanobot/workspace/`.
4. `uv tool install --editable` against a checked-out clone of nanobot.
5. Drops a systemd user unit (template).
6. `systemctl --user enable --now nanobot-peewee.service`.

Implementation choice: native TF provider vs `null_resource + remote-exec`.
Lean toward `null_resource` initially — no provider to write, just shell.
Promote to a custom provider only if we hit limits.

## Decisions

| # | Question | Default |
|---|----------|---------|
| 1 | Cloud provider | DigitalOcean droplet (sphelps.net). Generic via cloud-init so we can move. |
| 2 | Deploy mechanism | `null_resource` + `remote-exec` + `file` provisioners. |
| 3 | Secrets in state | Mark `sensitive = true`; encrypted backend (DO Spaces with SSE). |
| 4 | Config file generated where | Locally rendered, scp'd. Avoids leaking template logic into the host. |
| 5 | systemd unit | Per-agent unit (`nanobot-peewee.service`) so we can stop/start independently. |

## Concerns

- **TF state contains secrets.** Use encrypted backend. Never commit
  `.tfstate` to git. Plan/apply outputs need scrubbing.
- **Drift detection is awkward.** The bot will modify workspace files
  between applies — that's expected, not drift. Terraform should not
  manage workspace *contents*, only the *checkout*.
- **One bot per host or many?** P2 says one. Multi-agent in
  [[p3-multi-agent-fleet]].
- **Bootstrap order:** DO droplet must exist → SSH ready → deploy key
  set → clone → install. Provisioner chain or `depends_on`.

## Open questions

- Native provider vs `null_resource`. Native is nicer for idempotency
  but adds maintenance. Defer.
- Where does the nanobot binary come from? `uv tool install nanobot-ai`
  (PyPI) for stability, or `--editable git+...` for living-on-main? Per-agent flag.
- Re-applying when the workspace repo has commits ahead of last apply —
  do we pull or leave alone? Leave alone; the gateway already pulls
  on its own cadence (after [[p5-two-way-sync]]).

## Done when

- `terraform apply` from a clean state stands up a working bot.
- `terraform destroy` cleans the unit, repo checkout, deploy key, config.
- Telegram message round-trips through the deployed bot.
- State is recoverable after losing the local TF working dir (state
  lives in the backend).

## Related

- [[git-backed-agent-fleet]] — parent overview
- [[p1-auto-commit-nanobot]] — preceding phase
- [[p3-multi-agent-fleet]] — next phase
