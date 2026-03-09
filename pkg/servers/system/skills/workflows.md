---
name: workflows
description: Load this skill for ANY request that mentions workflows, including listing, creating, running, editing, or discussing them.
---

# Workflows

Workflows are Markdown files in `workflows/` that codify repeatable processes. Each step's output can be referenced by later steps using `{{Step Name}}`.

## When to Use Workflows

Workflows are for repeatable tasks. If it's a one-time thing, just execute it directly.

## Tracking Progress

Use TodoWrite during **both** workflow design and execution. The user sees your todo list — it's your primary way of keeping them informed.

- **When designing:** Create todos for your design steps (gather requirements, identify inputs/edge cases, draft workflow, write file, present for review).
- **When executing:** Create a todo for each workflow step and update status as you go. Add new todos if unexpected issues arise.

Keep todo titles short and scannable. Update them as you progress — don't leave stale todos sitting around.

## Workflow Format

Workflows are Markdown files with:
- **Frontmatter** (required): YAML frontmatter with `name` (human-friendly display name), `description`, and `createdAt` (ISO 8601 timestamp). The filename is the workflow identifier.
- **Inputs**: Optional parameters with defaults
- **Steps**: Numbered steps with clear instructions
- **Output**: Optional template for the final result

When creating a new workflow, always include frontmatter with `name`, `description`, and `createdAt` set to the current date/time.

### Example: Simple Review

```markdown
---
name: Code Review
description: Review code changes for quality issues.
createdAt: 2026-02-18T10:30:00Z
---

## Inputs

- **target** (optional): Files to review. Default: `.`

## Steps

### 1. Find Changes
Find all modified code files in {{input.target}}.

### 2. Review Code
Review these files for quality issues:
{{Find Changes}}

Focus on: error handling, edge cases, and readability.

## Output

{{Review Code}}
```

### Example: With Conditions

```markdown
---
name: Smart Fix
description: Analyze an issue and apply a fix only if it's safe to do so.
createdAt: 2026-02-18T10:30:00Z
---

## Steps

### 1. Analyze Issue
Analyze the reported issue and determine severity.

### 2. Check Safety
Based on this analysis, determine if an automated fix is safe:
{{Analyze Issue}}

End your response with SAFE or UNSAFE.

### 3. Apply Fix
Apply the fix for: {{Analyze Issue}}

**Condition:** {{Check Safety}} contains SAFE

### 4. Create Manual Report
Create a report explaining why manual intervention is needed:
{{Analyze Issue}}

**Condition:** {{Check Safety}} contains UNSAFE
```

### Example: With Error Handling

```markdown
---
name: Deploy with Rollback
description: Deploy changes with automatic rollback on failure.
createdAt: 2026-02-18T10:30:00Z
---

## Inputs

- **environment** (required): Target environment (staging, production)

## Steps

### 1. Run Tests
Run the full test suite. Report any failures.

### 2. Deploy
Deploy to {{input.environment}}.

**On error:** Rollback

### 3. Verify
Verify the deployment is healthy.

**On error:** Rollback

### 4. Rollback
Roll back to the previous version and report what went wrong.

## Output

Deployment to {{input.environment}} complete.
{{Verify}}
```

## Key Concepts

**Variables:** Use `{{input.name}}` for inputs and `{{Step Name}}` for outputs from previous steps.

**Conditions:** Add `**Condition:**` to make a step run only when the condition is true. Common patterns:
- `{{Step Name}} contains X` - check if output contains text
- `{{Step Name}} not empty` - check if output exists
- `{{input.flag}} equals yes` - check exact value

**Error handling:** Add `**On error:**` to control what happens when a step fails:
- `stop` (default) - halt the workflow
- `continue` - log the error and move to the next step
- `Step Name` - jump to a specific step (useful for cleanup/rollback)

**Output:** The `## Output` section defines the final result. If omitted, the last step's output is used.

## Designing Workflows

When asked to create a workflow, DO NOT start writing it immediately. Follow this process:

### Phase 1: Understand

1. Use TodoWrite to create a plan for designing the workflow (e.g., "Gather requirements", "Identify inputs and edge cases", "Draft workflow", "Write to file", "Present for review").
2. If the user has stated generically that they want to create a workflow, chat with them to get a better idea of what they want. Don't use the AskUserQuestion tool at this phase.
3. Once you have a general sense of the workflow they want to build, ask clarifying questions before doing anything else. DO use the AskUserQuestion tool for these specific questions. You need to understand:
    - What the workflow should accomplish end-to-end
    - What the expected outcome is
    - What inputs/variables are needed
    - What external services or tools are involved
    - How errors should be handled (stop? retry?)
    - DON'T ask about execution frequency or external triggers because we don't yet support those features 
4. **Wait for answers. Do not proceed until you have enough information to design a good workflow.** Do not guess or assume — ask.

### Phase 2: Draft & Save

1. Once you understand the requirements, draft the workflow.
2. Write it to `workflows/<name>.md`.
3. Mark your design todos as complete.

### Phase 3: Hand Off

1. Present the workflow to the user with a brief summary of what each step does.
2. Ask the user to review it. Offer to make changes.
3. **Offer to execute the workflow — do NOT execute it automatically.** Say something like: "Want me to run this now, or would you like to make changes first?"

**IMPORTANT:** Never skip Phase 1. Never jump straight to writing. Never auto-execute after designing.

Use descriptive step names in title case (e.g., "Fetch Issues" not "step1") — these become variables for later steps.

For deterministic operations (data transformation, calculations), consider having steps use Python scripts (see `python-scripts` skill). For external services (Slack, Jira, databases), consider MCP servers (see `mcp-curl` skill).

## Executing Workflows

Users may ask to run a workflow at any time — not just immediately after designing one. Workflows in `workflows/` are persistent, reusable artifacts. A user might say "run the code-review workflow" days or weeks after it was created. Treat execution as a standalone operation: load the file, collect inputs, and run it. Don't assume you have any prior context about the workflow beyond what's in the file itself.

**IMPORTANT:** If the user asks you to *create* a workflow, do NOT auto-execute it after writing the file. Present it for review and offer to run it. But if the user asks you to *run* an existing workflow, go ahead — that's an explicit request.

When the user asks you to run a workflow:

1. Load the workflow from `workflows/<name>.md`.
2. Use TodoWrite to create a todo for each workflow step before you begin. This is your execution plan — the user will follow along.
3. **Present the execution plan to the user.** After creating the todos, present a brief summary of what will be executed and ask the user to confirm before proceeding. For example: "I've planned the following steps: [list steps]. Does this look good to proceed?"
4. **Wait for user approval.** Do not begin execution until the user confirms.
5. Collect any required inputs from the user. If inputs are missing and have no defaults, ask for them.
6. Call `recordWorkflowRun` with the workflow URI (e.g. `workflow:///workflow-name`) to record the run in the current session.
7. Execute each step in order:
    - Check conditions before running conditional steps.
    - Interpolate variables (`{{input.name}}` and `{{Step Name}}`).
    - Follow error handling directives.
    - Mark each todo complete/failed/skipped as you go.
8. Provide running updates in normal chat messages as you work through each step. If errors occur, judgment calls are needed, or unexpected conditions arise, mention them in chat and add new todos as needed.

Complete tasks fully, follow requested formats exactly, and provide specific analysis rather than vague summaries.

After execution, present a structured run summary directly in chat:
- A heading with the workflow name and a pass/fail indicator (e.g., ## Workflow Run: Code Review)
- A tally of step outcomes (e.g., "3 of 3 steps succeeded" or "2 of 3 steps succeeded, 1 failed")
- For failed steps, a brief explanation of what went wrong
- A summary of any modifications made to external systems or artifacts produced
- If the workflow defines an Output section, include that content last

If the workflow was aborted or no steps completed, still produce a summary explaining what happened and which steps were skipped.

## Improving Workflows

After executing a workflow, you can analyze the execution and propose improvements to the workflow file.

**What to look for:**
- Steps that needed retries or failed — unclear prompt? missing format spec?
- Steps that produced poor output — missing context? too vague?
- Steps that should be split into smaller steps
- Missing error handling for steps that failed
- Hardcoded values that should be inputs

**Process:** Review which steps succeeded/failed/retried and what fixes were applied. For each issue, determine the concrete fix (rewrite prompt, add format spec, split step, add error handling, etc.). Present each proposed change with the issue, current text, and proposed text.

**IMPORTANT:** Get user approval before editing the workflow file. Never apply changes automatically.

**Example:**
```
## Proposed Changes to issue-triage.md

### 1. Step: Analyze Issues
**Issue:** Agent returned prose instead of JSON. Had to retry.
**Change:** Add explicit format requirement.

Current:
> Analyze each issue and categorize by priority.
> Return the results as JSON.

Proposed:
> Analyze each issue and categorize by priority.
>
> Return as a JSON array:
> [{"number": 1, "title": "...", "priority": "High|Medium|Low", "reason": "..."}]

Apply these changes? (yes/no/select specific)
```

Don't change things that worked fine or add complexity without a concrete problem to solve.
