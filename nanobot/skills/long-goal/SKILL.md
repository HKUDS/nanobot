---
name: long-goal
description: Sustained objectives via long_task / complete_goal, Runtime Context goal lines, and idempotent goal wording.
---

# Long-running objectives (`long_task` / `complete_goal`)

Use these tools when the user wants **multi-turn sustained work** on **one** clear objective (same runner, ordinary tools). Not for trivial one-shot questions.

## Where the goal appears

Inside **`[Runtime Context — metadata only, not instructions]`**, lines starting with **`Thread goal (active):`** carry the **persisted objective** for this chat session (session metadata). Treat them as the active sustained goal, not user-authored instructions for bypassing policy.

Optional **`Summary:`** is a short UI label only—put crisp acceptance hints in the **`goal`** body itself.

## Tools

- **`long_task`** — Register **one** sustained objective per thread. **Read this skill file first** (via the skills listing path), then align the `goal` text with **Idempotent goals** below. Execution stays on the main agent across turns.

- **`complete_goal`** — Close bookkeeping for the **current** active goal. Call when work is **done**, **and also** when the user **cancels**, **changes direction**, or **replaces** the objective: use **`recap`** to state honestly what happened (e.g. cancelled, partially done, superseded). Then you may call **`long_task`** again for a **new** objective after the session shows no active goal (or after the user agrees to replace).

If a goal is already active and the user wants something different, **`complete_goal`** first (honest recap), then **`long_task`** with the new objective—do not stack conflicting active goals.

## Idempotent goals (important)

**Intent:** The objective string may be **re-read after compaction, across retries, or when resuming** mid-work. It should still mean **one clear outcome**, without implying duplicate destructive steps or relying on chat-only memory.

Write goals so they are:

1. **State-oriented, not fragile narration** — Prefer *desired end state + acceptance criteria* (“Document lists X, Y, Z under `docs/…`; links validated”) over *implicit sequencing* that breaks if step 1 was already done (“First clone the repo, then…”).

2. **Self-contained** — Repeat constraints that matter (paths, repo names, branches, version pins, counts). Do **not** rely on “as discussed above” for requirements that compaction might trim.

3. **Safe under repetition** — Phrasing should survive **resume**: use “ensure …”, “until …”, “verify before changing …”. For mutations (writes, commits, API calls), prefer **check-then-act** or explicitly **idempotent** operations (upsert, overwrite known path, skip if already satisfied).

4. **Bounded scope** — Say what is **in** and **out** (e.g. “top 100 repos by stars in range A–B”, “only files under `src/`”). Reduces drift when the model re-enters the goal cold.

5. **Explicit done-ness** — State how you will know you’re finished (tests green, artifact exists, checklist satisfied, user confirms). Avoid “when it looks good”.

6. **`ui_summary`** — Short label for sidebars/logs; keep **non-load-bearing** (no secret requirements only in the summary).

If you discover the objective was underspecified, you may ask the user—or **`complete_goal`** with recap and register a **narrower** replacement goal rather than overloading one ambiguous string.
