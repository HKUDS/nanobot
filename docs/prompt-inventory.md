# Prompt Inventory

> Registry of all prompt template assets, their purpose, governance, and versioning.

## Template Directory

Source: `nanobot/templates/prompts/`
Loader: `nanobot/agent/prompt_loader.py` (`PromptLoader`)
Override: Place same-named files in `<workspace>/prompts/` (workspace-local wins).

## Templates

| File | Lines | Purpose | Consumed By |
|------|-------|---------|-------------|
| `classify.md` | 10 | Intent routing — maps messages to specialist agents | `Coordinator.classify()` |
| `compress.md` | 1 | Context compression — summarise conversation to ≤300 tokens | `summarize_and_compress()` |
| `critique.md` | 1 | Answer verification — JSON confidence + issues check | `AnswerVerifier` |
| `failure_strategy.md` | 4 | Tool failure recovery — analyse, propose alternative, execute | `_run_agent_loop()` REFLECT phase |
| `plan.md` | 8 | Planning — numbered 3–7 step plan with delegation policy | `_run_agent_loop()` PLAN phase |
| `progress.md` | 1 | Mid-loop reflection — assess steps complete vs remaining | `_run_agent_loop()` |
| `reflect.md` | 1 | Post-tool reflection — evaluate results, decide next action | `_run_agent_loop()` REFLECT phase |

## Integrity Verification

Prompt hashes are tracked in `prompts_manifest.json` (SHA-256).

**CI check**: `python scripts/check_prompt_manifest.py` runs in every CI build.
**Update after edits**: `python scripts/check_prompt_manifest.py --update`

## Change Process

1. Edit the template in `nanobot/templates/prompts/`
2. Run `python scripts/check_prompt_manifest.py --update` to regenerate hashes
3. Run `python -m pytest tests/test_prompt_regression.py` to verify key phrases
4. Commit both the template and updated `prompts_manifest.json`

## Workspace Overrides

Users can override any template by placing a file with the same name in
`<workspace>/prompts/`. The `PromptLoader` checks the workspace directory
first and falls back to the bundled templates. Overrides are **not** tracked
in the manifest — integrity checking applies only to bundled templates.

## Design Decisions

- **ADR-008**: Prompt management strategy — load from files, support workspace
  overrides, version via manifest hashes.
- Prompts are plain Markdown, not Jinja templates — no variable interpolation
  in the template files themselves. Dynamic content is injected by the calling
  code (e.g., tool definitions, conversation history).
