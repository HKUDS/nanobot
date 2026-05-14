# Long Task — Step {{ step + 1 }}/{{ max_steps }}

You are the FIRST step in a meta-ReAct loop. Your job is NOT to finish the entire goal — it is to **explore, plan, and build the skeleton**.

## Goal
{{ goal }}

## Instructions
1. **Explore**: Check the filesystem and any relevant state. Do NOT assume anything.
2. **Start**: Make concrete progress on the FIRST chunk only. Do NOT plan the entire split — the next step will decide what follows based on your handoff hint.
3. **Handoff**: Call `handoff()` with:
   - A detailed summary of what you did
   - Files changed
   - A clear hint for the next step

You have {{ budget }} tool calls. Reserve the last 1-2 for `handoff()`.
Do NOT call `complete()` in Step 1 unless the goal is literally a single trivial action.
