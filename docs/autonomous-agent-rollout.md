# Autonomous agent rollout

User-authorized implementation, 2026-09-12. This checklist records the full scope;
unchecked items are not claimed to be implemented or deployed.

## Acceptance checklist

- [ ] The next user session can manage all work from nanobot itself: durable
      project requirements/checkpoints/test evidence, continue/status/pause controls
      across Telegram/WebUI/TUI, and no dependency on this Codex conversation.
- [ ] Reverify the previous Apple/mail/profile integration rollout on the final version.
- [ ] Durable owner notification feed independent of Telegram delivery, delivery status,
      deduplication, shared read/action state, and recovery after restart.
- [ ] Proactive attention service: mail/calendar/task signals, event-driven evaluation,
      ten-minute catch-up, urgent delivery, hourly ordinary digest, silence without
      new information, source/reason/next action, snooze/done/take-action controls.
- [ ] On-demand attention summary uses the same items and state.
- [ ] Task progress, stop/resume/cancel, and explicit blocking reasons in all clients.
- [ ] Mail-rule proposals based on examples, impact preview, and explicit activation.
- [ ] TUI exposes Notifications above Main, canonical Telegram conversation,
      read-only notification composer, durable unread state, shared actions,
      runtime/integration status, reconnect, and task recovery.
- [ ] Remote TUI/session access over the existing WireGuard route and SSH key,
      without exposing or weakening the local Desktop bootstrap endpoint.
- [ ] Device node: authenticated enrollment/revocation, explicit device/workspace
      targeting, allowed capabilities, presence, durable jobs/results, offline queue,
      interruption reconciliation, no silent execution on a different machine.
- [ ] Devices and development status/actions in WebUI/TUI and chat commands.
- [ ] Self-development: evidence-backed deduplicated backlog, acceptance criteria
      and baseline before edits, isolated checkout/execution, meaningful tests,
      independent review, exact-artifact release, compatible rollback, outcome audit.
- [ ] Development limits: one active change, two repair attempts, daily budget,
      pause controls, and deployment only inside configured authorization policy.
- [ ] External supervisor runs every ten minutes, checks live gateway/task state,
      recovers stopped work, persists decisions, and avoids duplicate execution.
- [ ] Repository installers automate gateway and node setup, SSH host-key checking,
      existing WireGuard route validation, services, updates, and health verification.
- [ ] Update the local gateway and all affected services; verify actual runtime,
      reconnect/restart behavior, unit/integration/UI tests, and installed artifacts.
- [ ] Model-independent operation through provider adapters and capability detection;
      preserve Astra as the configured default, allow explicit model switching,
      and report unsupported capabilities without claiming equivalent behavior.
- [ ] Live Codex account limits in WebUI/TUI and on demand in chat: authoritative
      usage windows and reset times when available, last refresh and stale/error
      states; keep subscription quotas distinct from local token accounting.
- [ ] Additional stability controls: bounded retries, persisted checkpoints,
      clear hold reasons, recovery without duplicate side effects and visible health.

## Environment evidence

Initial worktree: `codex/integrations-stability-upstream`, clean. Four existing
services are active with zero restarts. The gateway container exposes `eth0`,
but no WireGuard interface or config; the tunnel may live on its host/router.
Existing SSH identity: `/root/.ssh/nanobot_ed25519` (contents never copied).
The remote node OS, WireGuard address, SSH user, and host-key verification remain
to be established before a real remote deployment can be verified.

## Implementation decisions

- Keep the central gateway as the owner of conversations, task records, and Astra.
- SSH over the existing WireGuard network is the required remote transport.
- Extend existing stores, tools, and clients rather than creating a second bot.
- Test fixtures never send mail/Telegram messages or mutate real calendar events.
- Development jobs cannot lower their own evaluation criteria or grant permissions.
- Record verified results below as work progresses; a passing narrow test does not
  imply that this entire checklist is complete.

## Verified results

Implementation in progress. The following are component results, not completion
of the full rollout:

- Durable notifications are written before ordinary/streamed-final dispatch;
  delivery receipts update the same row and preserve read state. Technical
  notifications record pending/delivered/uncertain/not-sent states separately.
- The read acknowledgement API acknowledges exactly the observed IDs. WebUI and
  TUI share its state; the notification composer is read-only. TUI opens the
  configured owner Main chat by default and pins Notifications above Main.
- Notification/backend/launcher regression selection: 128 passed.
- TUI protocol/menu/application selection: 127 passed.
- WebUI thread/sidebar/history selection: 138 passed after adding the regression
  for changing delivery status without adding another message.
- External supervisor and goal scanner heartbeat implemented; service templates
  installed locally. Gateway restarted, health is good, matching scanner heartbeat
  is present, and the supervisor timer is active. A manual check reported healthy
  with no restart attempts. Failure/restart decisions are covered by tests; full
  end-to-end recovery acceptance remains outstanding.
- Live existing integration verifier passed: IMAP6folders, CalDAV8calendars and
  11events, sleep disabled, all four original services active, shared histories
  canonical and ordered. Full final-version acceptance remains outstanding.
