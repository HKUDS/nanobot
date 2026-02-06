---
name: reasoning
description: Multi-step planning and reflection capabilities.
metadata: {"nanobot":{"emoji":"🧠","always":true}}
---

# Reasoning & Planning

Use `sequential_thinking` to break down complex tasks, plan ahead, and reflect on outcomes.

## When to use

- **Complex tasks**: If a task needs >1 step, plan it out.
- **Errors**: If something fails, reflect on why before retrying.
- **Exploration**: When you need to gather info before acting.

## Usage

The tool tracks your thought process:

1. **thought**: Your analysis or plan. Be specific.
2. **next_thought_needed**:
   - `true`: You need another thinking step (e.g., refining the plan).
   - `false`: You are ready to call a real tool (read_file, run_command, etc.).
3. **thought_number** / **total_thoughts**: Keep track of where you are.

### Advanced Features

- **Revisions**: If you change your mind, set `is_revision=true` and `revises_thought=N`.
- **Branching**: To explore alternatives, set `branch_from_thought=N` and `branch_id="alt-name"`.

## Example

**Step 1: Plan**
`sequential_thinking(thought="I need to fix bug X...", thought_number=1, total_thoughts=3, next_thought_needed=True)`

**Step 2: Refine**
`sequential_thinking(thought="Found the file...", thought_number=2, total_thoughts=3, next_thought_needed=False)`

**Step 3: Act**
Call `read_file(...)`
