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
- [x] Live Codex account limits in WebUI/TUI and on demand in chat: authoritative
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

### Development, quotas and remote terminal checkpoint

Verified on 2026-09-12 after deploying the development and quota controls:

- Full backend suite: **7763 passed, 53 skipped**, one existing aiohttp
  deprecation warning. WebUI: **1412 passed** across 93 files. TUI: **239 passed**.
  WebUI lint/build and TUI types/build passed. Full Ruff and strict BasedPyright
  passed. Later worker-recovery changes passed **150** development/operations/
  command tests; the remote CLI selection passed **194** tests. Strict types
  remained clean across 377 source files.
- Two real `openai-codex/gpt-6-astra` jobs edited a small isolated repository,
  passed fixed checks and a separate review, and produced an artifact marked
  `ready`. One worker ran as its own systemd service and completed across an
  actual gateway restart. These smoke runs consumed 6014 and 5805 reported
  tokens respectively. They did not modify production source or send messages.
- Runtime development controls are enabled for the canonical owner, with all
  **19 requirements** and five initial proposals seeded from
  [development-project.json](../deploy/development-project.json). The project
  remains paused while the rollout is being implemented here. `/development`,
  `/rozwoj`, the development tool and WebUI panel access the same durable store.
- The worker freezes baseline checks, isolates execution with bubblewrap, limits
  repair attempts and daily usage, and preserves interrupted preparation/build/
  verification stages. The ten-minute external supervisor can resume previously
  started development through an independent service with a durable retry cap.
- Live authenticated quota reads succeeded and confirmed that the Codex CLI
  account matches the gateway's OAuth account. Missing authentication was
  rejected. The displayed quota windows come from the provider, and stale reads
  keep their previous observation. `/limits` and the TUI/WebUI use the same source.
- After restarting the updated gateway, Apple/mail linkage, shared histories,
  Telegram, IMAP authentication/discovery and CalDAV checks passed again.
  All four configured services and the ten-minute supervisor timer were active.
- `nanobot remote` is implemented and tested, including parsing its generated
  configuration with the real OpenSSH client. It runs the TUI on the gateway
  through a verified SSH route; no new tunnel or exposed bootstrap is needed.
  A live second-device connection has **not** been verified without its details.

The entire backend suite also received an exploratory run inside the stricter
offline builder environment: **7736 passed, 63 skipped, 17 failed**. Those failures
involve real DNS assumptions, absent host passwd entries and attempts to build
missing WebUI assets offline. They are not counted as a passing acceptance run.
The configured starter checks are full Ruff plus development/operations/command
tests; their isolated preflight passed after provisioning the tokenizer data as
an explicit read-only dependency. Broad offline acceptance needs further work.

Production release/rollback, proactive attention and shared actions, collaborative
mail rules, full device execution and installers, complete client parity, and
final rollout acceptance remain unfinished. A `ready` development artifact is
not a deployed change. Setup and boundaries are documented in
[development controls](development-control.md) and [remote sessions](remote-session.md).

The first hosted run on the published increment passed the frontend, TUI on
Linux/Windows, Docker, mail and calendar jobs. Python jobs caught a duplicated
session-prefix literal in the remote launcher and two POSIX assumptions in new
tests. The launcher now uses the canonical session-identity function; the Codex
handshake test uses a real portable Python subprocess, and the installer test
checks parsed argument boundaries. Local revalidation: **7780 passed, 53 skipped**
plus 39 focused tests and clean strict types/lint. Hosted revalidation is pending;
the earlier failed runs are not reported as green.
