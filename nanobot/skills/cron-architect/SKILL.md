---
name: cron-architect
description: Guides the agent on how to construct robust, reliable, and stateful scheduled tasks (cron jobs) using a playbook-driven architecture.
---

# Cron Architect

This skill teaches you how to create robust scheduled tasks (cron jobs) for users. 

**DO NOT** just create a simple cron job with a plain text message if the task is complex (e.g., checking a website, tracking states, alerting on failures). Simple string messages cause the agent to lose context and fail when the job triggers.

Instead, you must use a **Playbook-Driven Architecture**.

## The Architecture
The core concept is that a cron job should execute a concrete, context-rich **Playbook**.
1. **Sandbox Directory**: Every complex task gets its own folder in `workspace/cron_jobs/<task_name>/`.
2. **Execution Scripts**: You must write Python scripts to handle the heavy lifting (crawling, data processing, file locking).
3. **State Management**: Your scripts should track their state in a local `state.json` file inside the sandbox directory.
4. **Playbook Markdown**: A `<task_name>_playbook.md` file that acts as the primary prompt/context for the agent when the job triggers.
5. **Registration**: The cron job is created by pointing to this playbook file.

## Step-by-Step Execution

When a user asks you to create a complex scheduled task (e.g., "Check Apple website for updates every day"):

### 1. Clarification (If needed)
Ask the user for specifics if the task is ambiguous:
- "What exact URL should I monitor?"
- "What constitutes an 'update'?"
- "Do you want me to alert you only on changes, or also if the check fails?"

### 2. Scaffold the Sandbox
Create a dedicated directory for the task:
```bash
mkdir -p workspace/cron_jobs/apple_checker
```

### 3. Write the Script (e.g., `check.py`)
Write a Python script that performs the actual check. 
**Crucial Requirements for Scripts:**
- **Concurrency**: Use Python file locks (e.g., `fcntl.flock` on Unix) to prevent overlapping runs.
- **State**: Read and write to `state.json` to know if an alert should be sent (e.g., only alert if the hash of the website changed).
- **Error Handling**: Use `try...except` blocks. Track consecutive errors in `state.json`. Only print an error to standard output if `consecutive_errors >= 3`.
- **Output**: The script should print a clear, concise result to standard output ONLY if an action needs to be taken by the agent (e.g., "NEW PRODUCT FOUND: ..."). If no action is needed, the script should print nothing or "NO_CHANGES".

### 4. Write the Playbook
Create `workspace/cron_jobs/<task_name>/playbook.md`. This is the context injected into the agent when the cron job fires.

Example `playbook.md`:
```markdown
# Scheduled Task: Apple Website Monitor

**Goal**: Check if Apple released new products.

**Instructions**:
1. Run `python workspace/cron_jobs/apple_checker/check.py`.
2. If the output says "NO_CHANGES", do not send any message to the user. Stop here.
3. If the output contains product details, summarize them beautifully and send them to the user.
4. If the output contains an error (e.g., failed 3 times), alert the user that the monitor is broken.
```

### 5. Register the Cron Job
Finally, register the job using the `cron` tool, providing the `playbook_path`:

```json
{
  "action": "add",
  "playbook_path": "cron_jobs/apple_checker/playbook.md",
  "cron_expr": "0 0 * * *"
}
```
*(Note: Do not pass a `message` if you pass a `playbook_path`. You may pass an empty string or a very brief title.)*

## Key Principles
- **Silent Rot vs Alert Fatigue**: The script should handle transient errors silently. Only alert the user if the script fails repeatedly.
- **File Locks**: Always lock a `.lock` file in the sandbox to prevent concurrent execution.
- **Stateless Agent, Stateful Script**: The agent wakes up with no memory of past runs. All state must live in `state.json`.
