---
name: claude-code
description: "Delegate tasks to Claude Code (Opus) for architecture, refactoring, and code review."
metadata: {"nanobot":{"emoji":"🤖","requires":{"bins":["claude"]}}}
---

# Claude Code Skill

Delegate complex tasks to Claude Code in non-interactive mode. Best for architecture, refactoring, and code review.

## When to use

- **Architecture / design** — system design, API design, module decomposition
- **Refactoring** — large-scale restructuring across multiple files
- **Code review** — deep analysis with contextual understanding

For template generation, batch operations, or test scaffolding, prefer the `codex` skill.

## Non-interactive execution (exec tool)

Always use `-p` (prompt) mode. Redirect stdout to a file to avoid output truncation on long responses (Claude Code has no `-o` flag).

```bash
# Basic: result to file (avoids truncation)
OUT=$(mktemp /tmp/claude-XXXXXX.txt)
cd <project_dir> && claude -p "<prompt>" --output-format text > "$OUT" 2>&1
cat "$OUT"

# Full-auto mode (skips permission prompts)
OUT=$(mktemp /tmp/claude-XXXXXX.txt)
cd <project_dir> && claude -p "<prompt>" --output-format text --dangerously-skip-permissions > "$OUT" 2>&1
cat "$OUT"
```

**Important:** Request a longer `timeout` (e.g. 300–600s) via the exec tool's `timeout` parameter — Claude Code tasks often take several minutes.

## Output formats

| Flag | Use case |
|------|----------|
| `--output-format text` | Human-readable, good for review results |
| `--output-format json` | Structured output, good for parsing |

## Environment notes

- `env_strip` automatically clears `ANTHROPIC_API_KEY` — Claude Code uses OAuth, not the API key
- Config: `~/.claude/settings.json`
- Auth: claude.ai OAuth (already logged in)
- Default permission mode: `bypassPermissions` (configured in settings.json)
