---
name: cron
description: Schedule automated recurring workflows, background monitors, and reminders. Use when the user wants to run tasks periodically (e.g., daily, hourly) or at a specific time in the future.
---

# Cron Scheduler & Playbook Manager

This skill helps you schedule background tasks. 

Because scheduled tasks run entirely autonomously in the future without user supervision, **stability, state management, and clear instructions are critical**. To achieve this, we separate tasks into "Simple" (stateless, single-step) and "Complex" (multi-step, stateful, requiring custom logic). 

For complex tasks, you will not just call a tool; you will design and write a **Playbook** inside the user's workspace that acts as a strict Standard Operating Procedure (SOP) for the future agent.

## Assessing Task Complexity

When a user asks to schedule a task, first assess its complexity:

*   **Simple Task:** Needs no memory of the past, uses standard built-in tools (e.g., "Remind me to drink water every 2 hours", "Summarize the latest HackerNews frontpage every morning"). 
*   **Complex Task:** Requires comparing data against previous runs (state), involves brittle web scraping, requires custom scripts, or needs to handle specific error conditions (e.g., "Check apple.com daily and tell me ONLY if there are new products compared to yesterday").

If the task is simple, go straight to **Scheduling**. If complex, you must first build a **Task Package**.

## The Anatomy of a Complex Task

All complex scheduled tasks MUST be stored in the user's workspace under the `.cron/tasks/` directory to keep the root directory clean. 

Organize the task into a dedicated folder:

```text
<workspace_root>/.cron/tasks/<task_name>/
├── playbook.md (required)      # The explicit instructions for the future agent
├── state.json (optional)       # Where the agent should read/write state between runs
├── scripts/ (optional)         # Custom Python/Bash scripts written by you to ensure stability
└── output/ (optional)          # Where reports, diffs, or downloaded assets are saved
```

*Why this structure?* Future agents running in a cron job lack the context of this current conversation. By grouping the playbook, state, and scripts together, you give the future agent a fully self-contained environment to succeed.

## Creating a Complex Task (The Workflow)

Do not just write a cron command and guess. Follow this sequence:

### 1. Interview and Design
If the user's request is vague, ask clarifying questions. What constitutes "a change"? Where should the output go? How should failures be handled?

### 2. Write Helper Scripts (If necessary)
If the task involves a fragile operation (like parsing a complex DOM or authenticating an API), **do not trust the future agent to figure it out on the fly.** Write a python or bash script, place it in `.cron/tasks/<task_name>/scripts/`, and test it now.

### 3. Write the `playbook.md`
Create the playbook. This is the most important step. Prefer imperative verbs and explain the *why*. Use the following structure:

```markdown
# [Task Name] Playbook

## Context & Objective
[Explain what this task does and why it runs. E.g., "This task runs daily to monitor for new product releases. We only want to alert the user if there is a DIFF from the previous day."]

## State Management
- **State File:** `.cron/tasks/<task_name>/state.json`
[Explain exactly how to use the state file. E.g., "Read the list of product IDs from state.json. If it doesn't exist, assume it's the first run. After fetching new data, ALWAYS overwrite state.json with the newest product IDs."]

## Execution Sequence
1. **Fetch Data:** [e.g., "Run `python .cron/tasks/<task_name>/scripts/fetch.py` to get the latest JSON."]
2. **Compare:** [e.g., "Compare the fetched data against state.json."]
3. **Act:** [e.g., "If there are new items, format a markdown report and send it to the user. If NO changes are found, you MUST exit silently without messaging the user."]

## Constraints & Error Handling
- [e.g., "If the website returns 403, do not retry. Just exit silently."]
- [e.g., "Only use built-in Python libraries like `urllib.request`, do not install `requests`."]
```

### 4. Schedule the Job

Once the playbook is written (and scripts are tested), schedule it. 

**Crucial: The `message` Parameter format**
The `message` you pass to the `cron` tool MUST be human-readable so that when the user lists their cron jobs, they know what it is. It MUST contain both a **Summary** and the **Playbook Path**.

**Format:**
`[Task Summary] - Playbook: <path/to/playbook.md>`

## Tool Usage: `cron`

Use the `cron` tool to interact with the scheduling daemon.

### Parameters
*   `action`: "add", "list", or "remove"
*   `name`: (Optional) A short, human-readable name for the job (e.g. "Apple Monitor"). Highly recommended for complex tasks.
*   `message`: (For "add") The task description or Playbook pointer. **Do not put complex instructions here.**
*   `every_seconds`: (Optional) Interval in seconds.
*   `cron_expr`: (Optional) Standard cron expression (e.g., "0 0 * * *").
*   `at`: (Optional) ISO datetime string for a one-time scheduled task.
*   `tz`: (Optional) IANA timezone (e.g., "America/Vancouver").

### Examples

**Adding a Simple Task:**
`cron(action="add", name="Tokyo Weather", message="Fetch weather for Tokyo and summarize", cron_expr="0 8 * * *")`

**Adding a Complex Task:**
`cron(action="add", name="Apple Product Monitor", message="Playbook: .cron/tasks/apple_monitor/playbook.md", cron_expr="0 0 * * *")`

**Listing Tasks:**
`cron(action="list")`
*(When listing tasks, help the user understand the currently scheduled jobs by reading the summaries in the messages.)*
