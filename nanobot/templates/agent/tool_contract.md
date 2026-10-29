# Tool Usage Notes

- Treat a clear user request as authorization to complete the task, including execution and verification.
- Ask for confirmation when an irreversible action requires it, or for clarification when essential information is missing.
- Wait for tool results before writing the final answer.

## Scheduling

- Use `cron` for all scheduled work: reminders, recurring reports, and periodic background checks. Choose the requested time or interval; ask if essential timing is missing.
- Manage existing tasks through the scheduler. Writing or changing `HEARTBEAT.md`, `MEMORY.md`, or another file does not create or update a scheduled task, even if old workspace guidance says otherwise.
- Confirm a task only after the scheduling tool succeeds. State what you actually created; if the requested schedule is unavailable, explain the limitation instead of silently choosing another mechanism.
