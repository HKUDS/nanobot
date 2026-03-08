---
name: script-git-manager
description: >
  Create and modify scripts in ~/.nanobot/workspace/test with strict Git versioning.
  Each script lives in its own directory with an isolated git repository.
  Always confirms creation plan before execution and reports progress at each step.
  Uses ~/.nanobot/workspace/venv for Python environment and package management.
---

# Script Git Manager Skill

This skill enforces a strict, deterministic workflow for creating and modifying scripts,
using Git as the sole state memory.
It is designed to prevent accidental file creation, uncontrolled refactors,
and loss of history.

---

## Scope

- Base directory: `~/.nanobot/workspace/test`
- Python virtual environment: `~/.nanobot/workspace/venv`
- One script = one directory = one git repository
- Git is mandatory and authoritative

---

## Python Environment

All Python-related operations (pip install, script execution) must use the virtual environment:

```bash
# Activate virtual environment
source ~/.nanobot/workspace/venv/bin/activate

# Install packages
pip install <package_name>

# Execute Python scripts
python <script_path>

# Deactivate when done
deactivate
```

**Always activate the venv before any pip or python command.**

---

## Creation Workflow

Use this skill **only when the user explicitly asks to create a new script**.

### Phase 1: Plan Confirmation

Before creating anything, present a detailed creation plan to the user:

```
📋 Script Creation Plan for: <script_name>

Directory: ~/.nanobot/workspace/test/<script_name>
File: <script_name>.<extension>
Language: <language>
Dependencies: <list of required packages, or "None">

Steps to execute:
1. Create directory ~/.nanobot/workspace/test/<script_name>
2. Initialize Git repository
3. Create script file <script_name>.<extension>
4. [If Python with dependencies] Activate venv and install: <packages>
5. Write script content
6. Create initial Git commit

Proceed with this plan? (yes/no)
```

**Wait for explicit user confirmation before proceeding.**

### Phase 2: Step-by-Step Execution

Execute each step sequentially and report progress after each one:

**Step 1: Create directory**
```bash
cd ~/.nanobot/workspace/test
mkdir <script_name>
```
Output: `✓ Created directory: ~/.nanobot/workspace/test/<script_name>`

**Step 2: Initialize Git**
```bash
cd <script_name>
git init
```
Output: `✓ Initialized Git repository`

**Step 3: Create script file**
```bash
touch <script_name>.<extension>
```
Output: `✓ Created file: <script_name>.<extension>`

**Step 4: Install dependencies (if Python with dependencies)**
```bash
source ~/.nanobot/workspace/venv/bin/activate
pip install <package1> <package2> ...
deactivate
```
Output: `✓ Installed Python packages: <package_list>`

**Step 5: Write script content**
```bash
# Write the actual script code to the file
```
Output: `✓ Script content written (<X> lines)`

**Step 6: Create initial commit**
```bash
git add .
git commit -m "Initial commit: <script_name>"
```
Output: `✓ Initial Git commit created`

**Final summary:**
```
✅ Script created successfully!

Location: ~/.nanobot/workspace/test/<script_name>/<script_name>.<extension>
Git status: Clean (1 commit)
[If Python] Virtual environment: ~/.nanobot/workspace/venv
```

---

## Modification Workflow

Use this skill **only when the user asks to modify an existing script**.

### Phase 1: Plan Confirmation

Before modifying, present the modification plan:

```
📝 Script Modification Plan for: <script_name>

Location: ~/.nanobot/workspace/test/<script_name>/<script_file>
Changes requested: <summary of user's request>

Steps to execute:
1. Enter script directory
2. Create checkpoint commit (current state)
3. Apply modifications: <specific changes>
4. [If new Python dependencies] Install via venv: <packages>
5. Commit changes with message: "<description>"

Proceed with this plan? (yes/no)
```

**Wait for explicit user confirmation before proceeding.**

### Phase 2: Step-by-Step Execution

**Step 1: Enter directory**
```bash
cd ~/.nanobot/workspace/test/<script_name>
```
Output: `✓ Entered script directory`

**Step 2: Create checkpoint**
```bash
git add .
git commit -m "Checkpoint before modification"
```
Output: `✓ Checkpoint commit created`

**Step 3: Apply modifications**
```bash
# Modify the script file as requested
```
Output: `✓ Modifications applied to <script_file>`

**Step 4: Install new dependencies (if applicable)**
```bash
source ~/.nanobot/workspace/venv/bin/activate
pip install <new_package>
deactivate
```
Output: `✓ Installed new packages: <package_list>`

**Step 5: Commit changes**
```bash
git add .
git commit -m "<concise description of the change>"
```
Output: `✓ Changes committed: "<commit_message>"`

**Final summary:**
```
✅ Script modified successfully!

Location: ~/.nanobot/workspace/test/<script_name>/<script_file>
Changes: <brief summary>
Git commits: 2 new commits (checkpoint + modification)
```

---

## Hard Constraints (Must Never Be Violated)

- Never create a new script unless explicitly instructed
- Never proceed without user confirmation of the plan
- Never skip progress reporting after each step
- Never create additional files unless explicitly instructed
- Never skip the pre-modification git commit
- Never modify files outside the target script
- Never rewrite git history
- Never use system Python - always use ~/.nanobot/workspace/venv
- Never assume missing intent

---

## Decision Rules

- If the script directory does not exist → creation workflow
- If the script directory exists → modification workflow
- If intent is ambiguous → ask for clarification, do nothing
- If plan is not confirmed → stop and wait for confirmation

---

## Progress Reporting Format

Use these symbols for consistency:

- `📋` Plan presentation
- `✓` Successful step completion
- `✅` Final success summary
- `⚠️` Warning or clarification needed
- `❌` Error or failure

Each step output should be concise (1-2 lines) but informative.

---

## Philosophy

Git is the memory.  
The filesystem is the contract.  
Confirmation prevents mistakes.  
Transparency builds trust.  
The venv isolates dependencies.
