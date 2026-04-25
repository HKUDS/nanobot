# Sendblue VPS Rollout TODO

Use this checklist to move the Sendblue iMessage deployment from smoke-test working to operationally stable.

## Stabilize Runtime

- [ ] Run `nanobot gateway --verbose` under `systemd` so it starts on boot and restarts after crashes.
- [ ] Confirm `journalctl -u nanobot -f` shows inbound Sendblue requests, model calls, and outbound replies.
- [ ] Reboot the VPS and verify nanobot and Caddy recover without manual SSH commands.
- [ ] Keep Sendblue pointed at the permanent domain webhook:
  `https://nanobot.ascentsolns.com/sendblue/webhook?secret=...`
- [ ] Keep the Sendblue dashboard Secret field empty unless the channel is updated to support Sendblue's exact secret/signature header format.

## Deployment Updates

- [ ] Document the active Git branch used on the VPS.
- [ ] Add a simple manual deploy command:
  `git pull`, `pip install -e .`, `systemctl restart nanobot`.
- [ ] Create `/root/deploy-nanobot.sh` for repeatable VPS updates.
- [ ] After manual deploys are reliable, add GitHub Actions over SSH to deploy after pushes to the chosen branch.
- [ ] Confirm a bad deploy can be rolled back by checking out the previous commit and restarting `nanobot`.

## Composio Tools

- [ ] Create or select the Composio MCP server/toolkit.
- [ ] Add `COMPOSIO_API_KEY` to `/etc/nanobot/nanobot.env`.
- [ ] Add `tools.composio.enabled`, `apiKey`, and `mcpServerId` to `~/.nanobot/config.json`.
- [ ] Verify the `you` profile uses `composioUserId: "you"` and gets a profile-specific MCP URL.
- [ ] Text the agent to connect the first real tool account and confirm it creates/reuses a Composio auth config and sends a Connect Link for user id `you`.
- [ ] Test an iMessage request that requires a Composio tool and confirm auth-link/tool behavior works.

## Multi-User Isolation

- [ ] Add girlfriend's phone number to `channels.sendblue.allowFrom`.
- [ ] Add a separate `gf` profile with its own workspace and `composioUserId`.
- [ ] Confirm your messages write only under `~/.nanobot/profiles/you`.
- [ ] Confirm her messages write only under `~/.nanobot/profiles/gf`.
- [ ] Connect her Composio accounts under user id `gf`.

## Daily-Use Validation

- [ ] Use the agent for a few days with only your phone.
- [ ] Check memory files and session files for expected profile separation.
- [ ] Confirm long replies are split correctly in iMessage.
- [ ] Confirm scheduled tasks/reminders deliver back through Sendblue.
- [ ] Review VPS disk usage and logs after several days of use.
