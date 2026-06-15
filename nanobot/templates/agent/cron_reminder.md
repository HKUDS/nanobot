The scheduled time has arrived. Execute this scheduled cron job now.

Rules:
- Speak directly to the user in their language.
- Do not narrate internal progress.
- Do not include user IDs.
- Your text response is NOT delivered to the user automatically. To send a notification, use the `message` tool explicitly.
- Only use `message` when there is something concrete and actionable to communicate. Silence is the correct behavior when there is nothing to report.

Cron job: {{ message }}
