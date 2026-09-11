# Heartbeat Tasks

<!--
When nanobot gateway starts with gateway.heartbeat.enabled=true, it registers a protected heartbeat cron job that reads this file periodically.

Use this file for recurring background checks that should stay quiet unless there is something useful to report. Regular cron jobs are different: they normally deliver each run's result back to the chat/session where they were created.

Keep recurring checks under "Active Tasks" and remove completed tasks. A file containing only headings and comments is skipped.
-->

## Active Tasks

