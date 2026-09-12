# Remote terminal session over WireGuard and SSH

The gateway keeps the conversation, model credentials, goals and development
project. A second computer only needs nanobot's CLI, an OpenSSH client, access
through the existing WireGuard route, and its already authorized SSH key.
`nanobot remote` starts the matching TUI **on the gateway** and transports its
terminal over SSH. Reconnecting opens the same Main or Notifications stream.

```bash
nanobot remote \
  --host 10.44.0.1 --network 10.44.0.0/24 --user owner \
  --identity ~/.ssh/nanobot_ed25519 \
  --known-hosts ~/.ssh/known_hosts \
  --executable /home/owner/.local/bin/nanobot \
  --config /home/owner/.nanobot/config.json
```

Replace the example address, CIDR and paths with the actual deployment. The
gateway executable must be from this fork and have its matching TUI dependencies
installed. The remote gateway currently needs a POSIX shell. The local SSH client
may run on Linux, macOS or Windows.

Use `--stream notifications` for the notification view, `--theme dark` for an
explicit appearance, or `--dry-run` to inspect the command without connecting.
The launcher requires an explicit network and rejects addresses outside it;
this is a target check, not proof that a route is encrypted. The existing
WireGuard route must already be configured on the computer, host or router.

The gateway host key must already be verified and present in `known_hosts`.
Missing or changed keys fail with OpenSSH's diagnostic. The launcher never adds
host keys automatically, creates tunnels, forwards an SSH agent, copies private
keys, or exposes the Desktop bootstrap endpoint. It disables ambient SSH proxy,
forwarding and password settings. A disconnect does not run work on the local
computer; durable gateway tasks and history remain available on reconnection.

This provides a remote session. Executing a task in the second computer's own
workspace requires the separate device-node workflow, whose unfinished scope is
tracked in [autonomous-agent-rollout.md](autonomous-agent-rollout.md).
