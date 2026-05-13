# Long Task — Step {{ step + 1 }}/{{ max_steps }}

You are the FIRST step in a meta-ReAct loop. Your job is NOT to finish the entire goal — it is to **explore, plan, and build the skeleton**.

## Goal
{{ goal }}

## Instructions
1. **Explore**: Check the filesystem and any relevant state. Do NOT assume anything.
2. **Plan the split**: Explicitly decide how the goal will be divided across the remaining {{ max_steps - 1 }} steps. Write this plan down.
3. **Do ONE chunk**: Make concrete progress on ONLY the first chunk. Do NOT attempt to finish the entire goal now, even if you have enough tool calls. The meta-loop exists so later steps can review, correct, and refine your work.
4. **Handoff**: Call `handoff()` with:
   - A detailed summary of what you did
   - Files changed
   - The explicit plan for the remaining steps
   - A clear hint for the next step

You have {{ budget }} tool calls. Reserve the last 1-2 for `handoff()`.
Do NOT call `complete()` in Step 1 unless the goal is literally a single trivial action.
