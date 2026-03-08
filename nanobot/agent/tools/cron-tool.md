# Cron Tool Guide (ACP Runtime)

In ACP mode, cron scheduling is managed by the ACP backend implementation.
Nanobot no longer provides `nanobot cron ...` CLI subcommands.

## Runtime file location

- Workspace root is the single runtime root.
- Cron store file path is:

`<workspace>/cron/jobs.json`

## Recommended ACP behavior

1. Read and write cron jobs from `<workspace>/cron/jobs.json`.
2. Keep the same `CronJob`/`CronSchedule` JSON shape used by native runtime.
3. Ensure cron edits are atomic (write temp file then replace).
4. Validate schedule fields before persisting.

## Operational notes

- Use `--dispatcher acp` to run ACP runtime.
- Optionally use `--acp-config` to override `dispatch.acp` at startup.
