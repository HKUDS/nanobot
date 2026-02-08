# Cron improvements: timezone support, store polling, edit command

## Summary

This PR improves the cron/scheduler service and CLI so that:

1. **New jobs are picked up without restart** — when the job list is empty or all jobs are disabled, the service still wakes periodically and reloads the store from disk, so jobs added via `nanobot cron add` (e.g. from the agent’s `exec` tool) are picked up without restarting the gateway.
2. **Cron expressions support timezones** — `nanobot cron add --cron "0 9 * * *" --tz Europe/Moscow` runs at 09:00 Moscow time; the server’s local time is no longer required.
3. **One-shot jobs default to delete-after-run** — `add_job(delete_after_run=...)` defaults to `True` when `schedule.kind == "at"`, so one-shot jobs don’t clutter the list.
4. **Jobs can be edited** — new `nanobot cron edit` command and `CronService.update_job()` to update name, message, schedule, deliver/to/channel.

## Changes

### `nanobot/cron/service.py`

- **POLL_WHEN_EMPTY_SEC (30)** — when there are no due jobs, the timer still fires at most every 30s; `_on_timer()` calls `_load_store(force_reload=True)` so the in-memory store is synced with the JSON file and new jobs (e.g. from CLI/exec) are picked up.
- **`_load_store(force_reload=False)`** — optional re-read from disk for the above.
- **`_compute_next_run()` for cron** — when `schedule.tz` is set, use `zoneinfo.ZoneInfo` and interpret the cron expression in that timezone; otherwise keep using server local time.
- **`_arm_timer()`** — always arms a timer (cap delay at POLL_WHEN_EMPTY_SEC) so the service keeps waking and reloading when the list is empty.
- **`add_job(..., delete_after_run=None)`** — when `None`, set to `True` for `kind=="at"`, else `False`.
- **`update_job(job_id, name=..., message=..., schedule=..., deliver=..., channel=..., to=...)`** — update existing job fields and recompute next run when schedule changes.

### `nanobot/cli/commands.py`

- **`cron add`** — add `--tz` option; pass `tz` into `CronSchedule` when using `--cron`.
- **`cron edit`** — new command: edit job by ID with `--name`, `--message`, `--every` / `--cron` / `--at`, `--tz`, `--deliver` / `--no-deliver`, `--to`, `--channel`. If only `--tz` is given for a cron job, keeps current expression and updates timezone.

## Heartbeat

Heartbeat logic is unchanged; no code changes in this PR. The same behavior as upstream is kept.

## Testing

- With no jobs (or all disabled), gateway stays running and `nanobot cron add ...` from another process is picked up within ~30s without restart.
- `nanobot cron add --cron "0 9 * * *" --tz Europe/Moscow` schedules next run at 09:00 Moscow time.
- `nanobot cron edit <id> --message "New task"` and `nanobot cron edit <id> --tz Asia/Yekaterinburg` update the job and next run.
- One-shot `--at` jobs are removed after run (or disabled if not delete_after_run).
