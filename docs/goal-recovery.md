# Native sustained-goal recovery watchdog

The gateway can optionally check stalled **explicit sustained goals** every ten
minutes and resume eligible work. Ordinary past requests are not automatically
resumed. This is a native gateway lifecycle service, not an external cron job or
a hidden recurring LLM prompt. Idle checks do not call the model or send messages.

## Activation (explicit opt-in)

Merge into the instance's existing configuration:

```json
{
  "gateway": {
    "goalRecovery": {
      "enabled": true,
      "intervalSeconds": 600,
      "maxBackoffSeconds": 3600
    }
  }
}
```

Defaults: `enabled: false`, interval 600 seconds, maximum retry backoff 3600
seconds. Interval validation permits 60–86400 seconds. The maximum effective
backoff is never shorter than the selected interval. These are startup settings;
restart the gateway in the usual controlled way after changing them. No service
is installed and no global configuration is modified by this feature. Unattended
checks require a running gateway (for example a managed gateway service); the
watchdog does not override on-demand last-client shutdown or restart the process.

At startup the existing recovery coordinator restores persisted final answers and
classifies interrupted checkpoints before channels accept input. With the opt-in,
a **newly discovered safe interruption** of an active sustained goal is marked
`webui_recovery.reason = goal_watchdog_scheduled` instead of creating a new generic
restart-confirmation gate. This does not mean the goal is finished: only checkpoint
restoration is complete. The watchdog waits a **full interval after startup**, then
checks for inactivity and persisted cooldown. Recent activity can delay recovery
until a later check. Existing confirmation requests are never retroactively approved.

## Safety and ownership

- Only goals whose status is exactly `active` and whose objective is nonempty are
  eligible. Completed, cancelled/canceled, blocked, paused, closed, and
  pending-confirmation goals stay unchanged.
- `/stop` durably pauses watchdog recovery. An explicit `/goal <task>` request
  can re-enable consideration after the cooldown; ordinary chat or `/help` cannot
  unpause the watchdog. This does not clear separate approval/recovery gates.
  The saved pause for the current goal identity takes precedence over every
  diagnostic hold, including transient session/goal status and approval flags;
  resolving those flags or restarting cannot erase `/stop`.
  A replaced goal has a new goal identity and does not inherit the old pause.
- Existing recovery states `awaiting_user`, `failed`, and `resuming`, dismissed
  recovery, pending user follow-ups, and explicit session/goal approval flags hold
  automatic work. Continue/dismiss remains the user's decision.
- Unknown/malformed checkpoints and interrupted tool calls are not replayed.
  A synchronized `tools_completed` checkpoint can be restored exactly once; an
  `awaiting_tools` checkpoint has unknown effects and requires human review.
- Recovery goes through the ordinary agent runtime, tool restrictions, and
  permissions. Authorization to pursue a goal is **not** authorization to repeat
  an uncertain side effect or bypass an approval.
- Busy sessions are skipped. A durable unique claim is written **before** enqueue;
  the agent revalidates it under its normal session lock. A second delivery,
  newer user input, cancelled goal, route change, or deleted session invalidates
  the claim. A watchdog turn is never injected into unrelated active work.
- One watchdog runs with the owning gateway. It assumes the existing gateway's
  single-instance ownership; it is not a multi-writer distributed scheduler.
- Disabled/unavailable channels are held. Unified sessions use their saved concrete
  last-channel route. Browser disconnection alone does not close a sustained goal;
  deleting its session prevents resurrection.

The internal continuation is not saved as a fabricated user message. Actual work
and its result use normal session persistence and channel delivery. Budget-sliced
continuations retain the existing goal runtime limits; watchdog polling does not
reset those limits.

## Startup recovery with the shared main inbox

When a SharedInbox is composed by the gateway, the recovery coordinator receives
an explicit **live resolver** for its active `telegram:<owner>` ↔ `shared-main`
mapping. Startup scan, Continue/Dismiss, completion events, and queued recovery
admission use that same identity. Neither a `telegram:*` prefix nor a saved
`last_channel` hint establishes shared ownership. The notifications pane and a
noncanonical `websocket:shared-main` file are not independent recoverable chats.

While that mapping is composed, ordinary WebUI actions stay in their concrete
`websocket:<chat>` sessions even if legacy global unified mode is configured;
`unified:default` is not adopted or modified by this coordinator's shared-inbox
scan. If the running inbox becomes inactive, shared actions/queued recovery fail
closed, with no fallback to a new WebSocket session or to unified history.
Without an inbox, the existing non-shared unified recovery policy is unchanged.

Safe journaled WebUI follow-ups are requeued in their canonical session with the
original journal IDs and `require_existing_session`. If they close a newly
classified safe interruption, its recovery reason is `followups_pending`; this
is not a fabricated user request or a watchdog continuation. The journal remains
on disk until the user rows are committed. Pending follow-ups still hold the goal
watchdog, so it cannot race them with an extra autonomous turn.

A saved follow-up is **not fresh consent**: `/stop`, independent approvals,
existing review/dismissal gates, and uncertain or malformed tool state prevent
requeue. These gates are checked again on journal admission, including a gate
created after startup enqueue. Uncertain tool results are materialized for review,
never replayed automatically. Held journal entries stay on disk for explicit
user review; Continue does not clear independent tool approval flags.

## Durable status and auditing

Session metadata `goal_recovery` records `status`, `reason`, `goal_id`, unique
`attempt_id`, cumulative `attempts`, consecutive `failures`, `updated_at`, and
`next_attempt_at` (Unix seconds), plus the latest 32 status transitions in `history`.
States include `queued`, `running`, `waiting`, `held`, `paused`, and `failed`.
Normal session atomic/fsynced saves persist these records and checkpoint restoration.
No credentials or extra conversation content are included in the audit history.

Failures use exponential backoff (with defaults: 20, 40, then 60 minutes), bounded
by `maxBackoffSeconds`; successful turns return to the normal ten-minute cooldown.
Cooldown survives restarts. A queued/running claim abandoned by an old gateway
can be replaced only after its persisted due time, with a new attempt ID and
increased failure count. A surviving uncertain tool checkpoint still blocks it.
Gateway shutdown preserves interruption eligibility; explicit user cancellation
pauses it. Scan errors are logged and isolated per session.

## Repeatable tests (no real gateway restart)

```sh
TEST_ROOT="$(mktemp -d /var/tmp/nr.XXXXXX)"
HOME="$TEST_ROOT/home" PYTHONDONTWRITEBYTECODE=1 /root/.nanobot/venv/bin/python -m pytest \
  -p no:cacheprovider --basetemp="$TEST_ROOT/tests" \
  tests/session/test_goal_recovery.py tests/session/test_recovery.py \
  tests/session/test_recovery_followup_gates.py tests/session/test_goal_state.py \
  tests/cli/test_shared_inbox_recovery.py -q
```

Use the repository's Python environment. An isolated HOME prevents legacy
instance-scoped WebUI transcript discovery from reading an active installation.
Tests instantiate fresh session managers and buses over saved data, advance an
injected clock, and exercise restart, duplicate delivery, busy/admission races,
stop/cancel/delete, combined pause/hold removal across restart, approval holds,
uncertain tools, durable backoff, and native lifecycle cancellation without network
calls or real-time sleeps. Shared-inbox composition tests instantiate the real
channel manager but never start its transports, run a provider, or send messages.
