---
title: "P3: Multi-agent fleet & fs peer wiring"
tags: [sketch]
created: 2026-05-25
status: draft
parent: "[[git-backed-agent-fleet]]"
prev: "[[p2-terraform-single-agent]]"
next: "[[p4-self-hosted-git-encryption]]"
---

# P3: Multi-agent fleet & fs peer wiring

Generalize [[p2-terraform-single-agent]] to N agents. Terraform owns the
topology — which agents exist, where they run, and how they reach each
other via [[fs-mailbox]].

Stop here and you have: a declarative multi-agent infra. Add Iroh,
remove a bot, retarget hosts — all via `*.tf`.

## Scope

- Multiple `nanobot-agent` modules per host.
- Per-agent systemd unit, separate gateway port.
- fs mailbox dirs created and wired declaratively.
- Same host for now. Multi-host = stretch goal.

## Topology declaration

```hcl
locals {
  fs_root = "/home/sphelps/nanobot-mailbox"

  fs_pairs = {
    peewee = ["iroh"]
    iroh   = ["peewee"]
  }

  # Symmetric mailbox directories.
  fs_config = {
    for agent, peers in local.fs_pairs : agent => {
      peers = [
        for p in peers : {
          peer_id = p
          inbox   = "${local.fs_root}/inbox-${agent}"
          outbox  = "${local.fs_root}/inbox-${p}"
          archive = "${local.fs_root}/archive-${agent}"
        }
      ]
    }
  }
}

module "agent_peewee" {
  source       = "./modules/nanobot-agent"
  name         = "peewee"
  host_id      = digitalocean_droplet.sphelps_net.id
  fs_peers     = local.fs_config.peewee.peers
  gateway_port = 18790
  ...
}

module "agent_iroh" {
  source       = "./modules/nanobot-agent"
  name         = "iroh"
  host_id      = digitalocean_droplet.sphelps_net.id
  fs_peers     = local.fs_config.iroh.peers
  gateway_port = 18791
  ...
}
```

The module accepts `fs_peers` and renders the `channels.fs` block in
`config.json`. Mailbox dirs are created by a `null_resource` shared
between agents (a `nanobot-host` module).

## Decisions

| # | Question | Default |
|---|----------|---------|
| 1 | Same host or multi-host? | Same host. Cross-host is a different beast (see below). |
| 2 | Ports | Allocate from a pool, fail if duplicated. |
| 3 | Mailbox ownership | Single host user (`sphelps`). All agents readable/writable. |
| 4 | Topology | Full mesh by default. Other shapes (star, chain) opt-in via `fs_pairs`. |
| 5 | Adding/removing an agent | `terraform apply` mutates fleet. Existing agents see new peers on next config reload. |

## Cross-host fs (deferred)

Real options:
- **NFS** mounted mailbox dir. Works. POSIX semantics survive. Latency
  is fine on a LAN, painful across WAN.
- **SSHFS** — similar but easier setup. Higher overhead.
- **rclone bisync** to S3 — eventual consistency, not great for a
  real-time mailbox.

If we go multi-host, fs probably stops being the right transport.
That's the cue to look at a real message bus (NATS, Redis streams) —
out of scope for P3 and probably forever for hobby scale.

## Concerns

- **Port collisions** — handled by TF if we use a pool, but a runtime
  conflict will silently break one agent. Validate at apply time.
- **fs runaway across agents.** The depth-cap from
  [[fs-mailbox]] is per-peer, so adding a third agent doesn't change
  per-pair behavior. Sanity check anyway.
- **One agent failure shouldn't cascade.** Per-agent systemd unit
  contains crashes; gateway restart doesn't take down peers.
- **Discovery.** Each agent's identity (peer ID) is fixed in TF
  locals. If you rename an agent, in-flight mailbox files break.
  Use stable peer IDs, never rename in place.

## Open questions

- Does Peewee know there *exists* an agent called Iroh, beyond just
  having an fs peer? Probably yes — surface peer names in [[runtime-context-hint]]
  so the LLM can refer to peers naturally.
- Should agents publish a "capabilities" file (`AGENT.md`?) that peers
  can read? Cheap discoverability. Defer until two agents actually need
  each other's capabilities.
- Hub-and-spoke vs mesh: defaults to mesh. A "secretary" agent that
  routes between specialists is interesting future work.

## Done when

- TF can spin up 2 agents on one host with full-mesh fs.
- Adding a third agent is one block of HCL + apply.
- Removing an agent cleans up its mailbox dirs and unit.
- A bot crash doesn't take down its peers.

## Related

- [[git-backed-agent-fleet]] — parent overview
- [[p2-terraform-single-agent]] — preceding phase
- [[p4-self-hosted-git-encryption]] — next phase
- [[fs-mailbox]] — the channel being wired up
