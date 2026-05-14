---
name: thread-goal
description: Thread objectives via long_task / complete_goal and Runtime Context goal lines.
always: true
---

# Thread goal (`long_task` / `complete_goal`)

## Where the goal appears

Inside **`[Runtime Context — metadata only, not instructions]`**, lines starting with **`Thread goal (active):`** are the **persisted thread objective** for this chat session (same source as session metadata). Treat them as the active sustained goal, not user-authored instructions for bypassing policy.

Optional **`Summary:`** is a short label only.

## Tools

- **`long_task`** — Register **one** sustained objective per thread. Execution stays on the main agent; use normal tools across turns. Not for trivial one-shot questions.

- **`complete_goal`** — Close bookkeeping for the **current** active goal. Call it when work is **done**, **and also** when the user **cancels**, **changes direction**, or **replaces** the objective: use **`recap`** to state honestly what happened (e.g. cancelled, partially done, superseded). Then you may call **`long_task`** again for a **new** objective after the session shows no active goal (or after the user agrees to replace).

If a goal is already active and the user wants something different, **`complete_goal`** first (honest recap), then **`long_task`** with the new objective—do not stack conflicting active goals.
