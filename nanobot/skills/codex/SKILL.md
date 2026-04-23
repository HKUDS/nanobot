---
name: codex
description: "Delegate tasks to Codex CLI for template generation, batch operations, and test scaffolding."
metadata: {"nanobot":{"emoji":"⚡","requires":{"bins":["codex"]}}}
---

# Codex Skill

Delegate tasks to Codex CLI in non-interactive mode. Best for template generation, batch operations, and test scaffolding.

## When to use

- **Template / boilerplate generation** — scaffolding new files, components, configs
- **Batch operations** — repetitive changes across many files
- **Test scaffolding** — generating test stubs and fixtures

For architecture, refactoring, or code review, prefer the `claude-code` skill.

## Non-interactive execution (exec tool)

Use `exec --full-auto` mode. Use `-o` to write the final response to a file — this avoids output truncation when results are long.

```bash
# Basic: result to file (avoids truncation)
codex exec --full-auto -C <project_dir> -o /tmp/codex-result.txt "<prompt>"
cat /tmp/codex-result.txt

# With JSON event stream (for progress monitoring)
codex exec --full-auto --json -C <project_dir> "<prompt>"

# Specify sandbox mode
codex exec --full-auto -s workspace-write -C <project_dir> -o /tmp/codex-result.txt "<prompt>"
```

**Important:** Request a longer `timeout` (e.g. 300–600s) via the exec tool's `timeout` parameter — Codex tasks often take several minutes.

## Key flags

| Flag | Purpose |
|------|---------|
| `--full-auto` | Auto-approve + workspace-write sandbox |
| `-o <file>` | Write final message to file (avoids truncation) |
| `--json` | JSONL event stream to stdout |
| `-C <dir>` | Working directory |
| `-s <sandbox>` | Sandbox mode override |

## Environment notes

- Config: `~/.codex/config.toml`
- Model: gpt-5.3-codex
- MCP servers: playwright, pyright
