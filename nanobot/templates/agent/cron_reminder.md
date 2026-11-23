The scheduled time has arrived. Execute this scheduled cron job now and report the result to the user in the same session.

Rules:
- Return the result as a normal reply. nanobot delivers it to this task's saved chat.
- Use the message tool only for file attachments or sends explicitly required by the task. Keep any explicit recipients in the task instructions.
- Speak directly to the user in their language.
- Do not narrate internal progress.
- Do not include user IDs.
- Do not add status reports like "Done" or "Reminded" unless they are the natural response.

Cron job: {{ message }}
