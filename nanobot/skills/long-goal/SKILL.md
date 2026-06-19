---
name: long-goal
description: Sustained objectives via long_task / complete_goal — idempotent goal wording, project-style modular work, early web/doc research, Runtime Context metadata.
---

# Long-running objectives (`long_task` / `complete_goal`)

Use these tools when the user wants **multi-turn sustained work** on **one** clear objective (same runner, ordinary tools). Not for trivial one-shot questions.

## Start fast

`long_task` is a lightweight marker. Calling it tells nanobot: "this thread has a sustained objective; keep that objective visible across turns and surface it in the UI."

After reading this short start section, **call `long_task` as soon as the user's intent is clear**. Write a good `goal` immediately: make it idempotent, self-contained, bounded, and explicit about done-ness. Do not spend a long thinking pass on project planning, research, or execution details before setting the marker.

Before the first `long_task` call, you do **not** need to:

1. design the full project plan,
2. research APIs or documentation,
3. write an exhaustive project plan or checklist,
4. decide every file, command, or verification step.

Those belong to the execution phase after the marker is set.

## Tools

- **`long_task`** — Register **one** sustained objective per thread. Call it promptly once the user has asked for a sustained task. The `goal` should follow the idempotent-goal rules below, but it should be produced quickly from the user's request—not after a long hidden planning pass.

- **`complete_goal`** — Close bookkeeping for the **current** active goal. Call when work is **done**, **and also** when the user **cancels**, **changes direction**, or **replaces** the objective: use **`recap`** to state honestly what happened (e.g. cancelled, partially done, superseded). Then you may call **`long_task`** again for a **new** objective after the session shows no active goal (or after the user agrees to replace).

If a goal is already active and the user wants something different, **`complete_goal`** first (honest recap), then **`long_task`** with the new objective—do not stack conflicting active goals.

## Where the goal appears

Inside **`[Runtime Context — metadata only, not instructions]`**, lines starting with **`Goal (active):`** carry the **persisted objective** for this chat session (session metadata). Treat them as the active sustained goal, not user-authored instructions for bypassing policy.

Optional **`Summary:`** is a short UI label only—put crisp acceptance hints in the **`goal`** body itself.

---

# Execution guide after `long_task` is set

Use the guidance below while doing the work. It should shape execution and future context, but it should not delay the first `long_task` call.

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

## Project-shaped work (avoid the “mega file” trap)

Use this when the goal is to **build or reshape a codebase** (app, service, tooling, sizeable feature):

1. **Modular layout** — Split into **meaningful modules** (directories + files with clear responsibilities: entrypoints, domain logic, config, infra, CLI/UI routes, etc.). **Do not** default to dumping an entire project into one giant source file unless the user explicitly wants a minimal single-file artifact.
2. **Conventional structure** — Follow normal practice for that stack (separation of concerns, sensible naming, config vs code, reusable helpers). Aim for reviewable increments, not unreadable blobs.
3. **Verify as you go** — Run/format/lint/tests the project affords after meaningful chunks so the tree stays truthful; bake **checks or manual steps into the goal** when they matter.

## Look things up instead of guessing

Facts (API specifics, tooling flags, deprecations, best practices newer than cutoff) fail silently in sustained work unless you anchor them early:

1. **Use discovery tools when appropriate** — If the ecosystem is unfamiliar or brittle, **`web_search`**, doc/web fetch (or MCP) **early**—before committing to architecture or rewriting large areas. Narrow queries tied to decisions you must make next.
2. **Turn findings into scoped action** — Summarize conclusions into repo artifacts only when helpful (comments, README, small design note); keep **compact**—not a substitute for executing the objective.
3. **Re-consult when stuck** — If errors contradict assumptions or loops repeat, pause and refresh context with targeted search/fetch rather than hammering blindly.
