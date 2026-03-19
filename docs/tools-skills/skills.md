# Skills system guide

Skills are knowledge extensions packaged in Markdown. Each skill provides procedures, command examples, and reusable resources. Nanobot decides when to load a skill based on its description—no manual triggering required.

---

## What is a skill?

A skill is a directory containing at least a `SKILL.md` file with:

- **YAML frontmatter** describing the skill name, purpose, and activation conditions
- **Markdown body** that the agent loads into context when the skill is triggered

Skills follow the [OpenClaw](https://github.com/openclaw/openclaw) specification and remain compatible with the OpenClaw ecosystem.

---

## Skill format

```
skill-name/
├── SKILL.md              # required
└── (optional resources)
    ├── scripts/          # executable scripts (Python, Bash, etc.)
    ├── references/       # reference docs (loaded on demand)
    └── assets/           # output artifacts (templates, images, etc.)
```

### SKILL.md structure

```markdown
---
name: my-skill
description: >
  What this skill does, when it should trigger, and why it matters.
  Include trigger phrases and usage scenarios.
always: false    # Set to true for resident skills like memory
---

# Skill title

Detailed instructions go here.
```

#### Frontmatter fields

| Field | Required | Description |
|------|------|------|
| `name` | yes | Skill identifier (lowercase letters, digits, hyphens) |
| `description` | yes | Explain the trigger phrases and functionality |
| `always` | no | Set to `true` to load the skill permanently (default false) |
| `homepage` | no | Link to related resources |
| `metadata` | no | Nanobot-specific extensions (emoji, dependencies, etc.) |

> **Important:** `description` is the single most critical part for triggering. Include concrete keywords, scenarios, and actions.

---

## Installing skills

### Built-in skills

Nanobot automatically loads every skill under `nanobot/skills/` at startup.

### Custom skills

Place skill folders inside your workspace `skills/` directory:

```
~/.nanobot/workspace/
└── skills/
    └── my-skill/
        └── SKILL.md
```

Restart nanobot to load new skills.

### Install from ClawHub

```bash
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
```

Run a new workspace session after installation.

---

## Built-in skills

### GitHub (`github`)

Interact with GitHub via the `gh` CLI to manage issues, PRs, and workflows.

**Prerequisite:** Authenticate with `gh auth login`.

```bash
gh pr checks 55 --repo owner/repo
gh run list --repo owner/repo --limit 10
gh run view <run-id> --repo owner/repo --log-failed
gh issue list --repo owner/repo --json number,title \
  --jq '.[] | "\(.number): \(.title)"'
```

**Trigger phrases:** “review PR”, “CI failure”, “list issues”, “github”, “gh CLI”

---

### Weather (`weather`)

Use `wttr.in` and Open-Meteo for free weather reports.

```bash
curl -s "wttr.in/Taipei?format=3"
# Output: Taipei: ⛅️ +22°C
curl -s "wttr.in/Taipei?format=%l:+%c+%t+%h+%w"
curl -s "wttr.in/Taipei?T"
curl -s "wttr.in/Taipei.png" -o /tmp/weather.png
```

**Format codes:** `%c` status, `%t` temperature, `%h` humidity, `%w` wind, `%l` location, `%m` moon phase

**Units:** `?m` for metric (default), `?u` for imperial

**Open-Meteo fallback (JSON):**

```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=25.04&longitude=121.53&current_weather=true"
```

**Trigger phrases:** “weather”, “temperature”, “will it rain”, “forecast”

---

### Summarize (`summarize`)

Use the `summarize` CLI to summarize URLs, PDFs, and YouTube videos.

**Prerequisite:** Install `summarize` (`brew install steipete/tap/summarize`)

```bash
summarize "https://example.com/article" --model google/gemini-3-flash-preview
summarize "/path/to/document.pdf" --model google/gemini-3-flash-preview
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto --extract-only
```

**Common flags:**

| Flag | Description |
|------|------|
| `--length short|medium|long|xl|xxl|<chars>` | Control summary length |
| `--extract-only` | Only extract text without summarizing |
| `--json` | Output JSON |
| `--youtube auto` | Fetch YouTube transcript |

**Supported API keys:** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`

**Trigger phrases:** “summarize this link”, “what does this YouTube video say”, “please summarize this article”, “transcribe”

---

### Tmux (`tmux`)

Control tmux sessions for interactive terminal work.

```bash
SOCKET="${TMPDIR:-/tmp}/nanobot.sock"
SESSION=nanobot-work

tmux -S "$SOCKET" new -d -s "$SESSION" -n shell

tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -- \
  'PYTHON_BASIC_REPL=1 python3 -q' Enter

tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -l -- "print('hello')"
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 Enter
tmux -S "$SOCKET" kill-session -t "$SESSION"
```

**Parallel agents:**

```bash
SOCKET="${TMPDIR:-/tmp}/codex-army.sock"
for i in 1 2 3; do
  tmux -S "$SOCKET" new-session -d -s "agent-$i"
done
tmux -S "$SOCKET" send-keys -t agent-1 "claude --dangerously-skip-permissions 'Fix bug X'" Enter
```

**Prerequisite:** tmux on macOS/Linux

**Trigger phrases:** “use tmux”, “interactive terminal”, “background execution and monitoring”

---

### Memory (`memory`)

Two-layer persistent memory stores facts and histories across workspaces.

**This skill is marked `always: true`.**

#### File structure

| File | Description | Loading |
|------|------|---------|
| `memory/MEMORY.md` | Long-term facts (preferences, context) | Always loaded into context |
| `memory/HISTORY.md` | Append-only timeline entries prefixed with `[YYYY-MM-DD HH:MM]` | Read on demand |

#### Updating memory

Use `edit_file` or `write_file`:

```python
edit_file(
    path="memory/MEMORY.md",
    old_text="## Preferences\n",
    new_text="## Preferences\n- Prefers dark theme\n"
)
```

#### Searching history

```bash
read_file(path="memory/HISTORY.md")
exec(command='grep -i "keyword" memory/HISTORY.md')
exec(command='python3 -c "from pathlib import Path; text = Path(\'memory/HISTORY.md\').read_text(); print('\n'.join([l for l in text.splitlines() if 'keyword' in l.lower()][-20:]))"')
```

Older conversations are summarized to `MEMORY.md` as the token count exceeds thresholds.

---

### Cron skill (`cron`)

Provides guidance for scheduling using the `cron` tool. See the [built-in tools guide](tools.md) for the full Cron section and examples.

---

### ClawHub (`clawhub`)

Search and install public skills from ClawHub without API keys. Use natural language queries.

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
npx --yes clawhub@latest update --all --workdir ~/.nanobot/workspace
npx --yes clawhub@latest list --workdir ~/.nanobot/workspace
```

> **Important:** Always add `--workdir ~/.nanobot/workspace` so skills land in the workspace.

Restart the workspace to load new skills.

**Prerequisite:** Node.js (includes `npx`)

**Trigger phrases:** “find a skill”, “install a skill”, “what skills exist”, “update skills”

---

### Skill creator (`skill-creator`)

Provides a full workflow for designing custom skills.

#### Steps to build a new skill

1. **Understand the need:** Gather concrete trigger examples
2. **Plan content:** Decide which scripts, references, and resources are required
3. **Initialize:** Run `init_skill.py` to scaffold folders
4. **Edit content:** Author `SKILL.md` and additional resources
5. **Package:** Run `package_skill.py` to produce a `.skill` artifact
6. **Iterate:** Refine based on usage insights

```bash
scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills
scripts/init_skill.py my-skill --path ~/.nanobot/workspace/skills \
  --resources scripts,references
scripts/package_skill.py my-skill/
```

**Trigger phrases:** “build a new skill”, “design a skill”, “I want to package a skill”

---

## Creating a custom skill

### Minimal example

```
~/.nanobot/workspace/skills/
└── my-helper/
    └── SKILL.md
```

```markdown
---
name: my-helper
description: >
  Assists with internal Jira tickets. Trigger when the user asks about Jira tasks
  (querying, creating, updating, assigning).
---

# Jira Helper

## Query a ticket

```bash
curl -H "Authorization: Bearer $JIRA_TOKEN" \
  "https://company.atlassian.net/rest/api/3/issue/PROJ-123"
```

## Create a ticket

```bash
curl -X POST -H "Authorization: Bearer $JIRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fields": {"project": {"key": "PROJ"}, "summary": "Title", "issuetype": {"name": "Task"}}}' \
  "https://company.atlassian.net/rest/api/3/issue"
```
```

### Design principles

- **Description controls triggering:** Clear scenarios and phrases determine whether the agent loads the skill
- **Keep it concise:** Skills contribute to the shared context window; avoid verbose passages
- **Lazy-load details:** Move lengthy docs into `references/` so they load only when needed
- **Scripts over repeated text:** Put reusable code into `scripts/` instead of having the agent regenerate it every time

### Naming rules

- Use lowercase letters, digits, and hyphens
- Prefer verb phrases (e.g., `fix-pr-comments`, `deploy-aws`)
- Keep the name under 64 characters
- Match the folder name with the `name` field

---

## Compatibility with OpenClaw

Nanobot skills mirror the OpenClaw format:

- `name` and `description` mean the same thing
- `always: true` has the same effect
- Directory structure (`scripts/`, `references/`, `assets/`) matches
- `.skill` packaging (zip) is interoperable

Nanobot-specific `metadata` fields (`emoji`, `requires`, `install`) are ignored by OpenClaw clients.
