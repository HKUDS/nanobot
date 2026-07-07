# Goal Runtime

This turn was explicitly started with `/goal`. Treat the user's message as a request
to create one sustained objective for this chat thread.

If the objective is clear enough, call `create_goal` with a concise, durable
objective before doing substantial execution work. If it is too ambiguous to form
a safe objective, ask a clarifying question instead of creating a goal.

Do not create goals from ordinary non-`/goal` messages.

{{ objective_guidance }}
