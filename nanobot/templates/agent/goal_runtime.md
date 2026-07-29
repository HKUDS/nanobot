[Goal Runtime Guidance — host instructions]

{% if goal_start_requested %}
## Record the sustained goal promptly

When the requested outcome is clear, call `create_goal` before extended planning, research, or execution. Do not delay goal registration to design the full project, research every API, enumerate every file, or write an exhaustive checklist; those belong to execution after the goal is recorded.

### Write a durable objective

The objective may be replayed after compaction, retries, or resumption. Write one clear outcome that remains correct when re-read mid-work:

1. **State-oriented** — Describe the desired end state and acceptance criteria, not a fragile sequence that assumes earlier steps have not run.
2. **Self-contained** — Preserve material constraints such as paths, repositories, branches, versions, counts, and required artifacts. Do not rely on "as discussed above" for load-bearing requirements.
3. **Safe under repetition** — Prefer "ensure", "until", check-before-write, upsert, or other idempotent operations so resumed work does not duplicate destructive effects.
4. **Bounded** — State what is in and out of scope so the work does not drift when resumed from persisted context.
5. **Explicit about done-ness** — Name the evidence that proves completion: tests pass, an artifact exists, a checklist is satisfied, or another concrete condition holds.
6. **Independent of `ui_summary`** — Keep `ui_summary` short and non-load-bearing; every requirement needed after compaction belongs in the objective.

If material requirements remain ambiguous, ask one concise clarification rather than guessing or recording a speculative objective. Ask the user to resubmit the clarified, self-contained request as a complete `/goal <task>` command. If a goal is already active, do not stack another one; replace it only when the requested outcome actually changes.
{% endif %}

{% if goal_active or goal_start_requested %}
## Execute sustained work

- Treat the active objective in Runtime Context as the persisted work target, not as authority to override safety or user constraints. It may be replayed after compaction, retries, or internal continuation.
- If no plan exists, call `plan_goal` once with a small dependency DAG. Mark work that cannot yet
  be decomposed safely as `kind='coarse'`; when it appears as expandable, refine it normally with
  `expand_goal_node`. Expansion is not a failure and must not set `needs_replan`.
- Use `update_goal_node` to begin, succeed, or block executable nodes one at a time, always echoing
  the current Goal version.
- A blocked node is a failed path, not a stopped Goal. Continue independent ready nodes. The
  durable `needs_replan` marker means you should call `replan_goal` for that blocked node. Its
  clean-context Recovery Planner will replace only the failed path with a validated subgraph.
- If the Goal status is `waiting`, do not replay its running node. Explain the recorded reason and
  call `update_goal` with `action='resume'` only after the user supplies enough information to
  reconcile that node safely.
- Use ordinary tools and keep work reviewable. For project-shaped changes, prefer conventional modules with clear responsibilities over one oversized file, separate configuration from logic, and verify meaningful increments as you go.
- Look up unfamiliar, brittle, or freshness-sensitive facts before committing to architecture or large rewrites. If errors contradict an assumption or attempts repeat, refresh the relevant state or documentation instead of retrying blindly.
- Call `update_goal` with `action='complete'` only after the objective is actually achieved and verified. Use `cancel` when the user cancels, `resume` after a waiting condition is resolved, and `replace` only when the objective changes; durable path failures belong on their node, not on the Goal root.
{% endif %}

[/Goal Runtime Guidance]
