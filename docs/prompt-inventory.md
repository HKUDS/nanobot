# Prompt Inventory

> Registry of all prompt template assets, their purpose, governance, and versioning.

## Template Directory

Source: `nanobot/templates/prompts/`
Loader: `nanobot/context/prompt_loader.py` (`PromptLoader`)
Override: Place same-named files in `<workspace>/prompts/` (workspace-local wins).

## Templates

| File | Purpose | Consumed By |
|------|---------|-------------|
| `compress.md` | Context compression — summarise conversation | `summarize_and_compress()` |
| `consolidation.md` | Memory consolidation instructions | `ConsolidationPipeline` |
| `critique.md` | Answer verification — JSON confidence + issues check | Self-check pass in `TurnRunner` |
| `deck_synthesis.md` | Deck/presentation synthesis | Skill-specific |
| `delegation_agent.md` | Delegation agent system prompt | `DelegationDispatcher` |
| `delegation_schema.md` | Delegation response schema | `DelegationDispatcher` |
| `extractor.md` | Memory event extraction instructions | `MemoryExtractor` |
| `failure_strategy.md` | Tool failure recovery strategies | `TurnRunner` error handling |
| `heartbeat.md` | Heartbeat/scheduled task instructions | `HeartbeatService` |
| `identity.md` | Core agent identity and behavioral rules | `ContextBuilder` system prompt |
| `memory_header.md` | Memory context header for prompts | `ContextBuilder` |
| `micro_extract.md` | Lightweight memory extraction | `MicroExtractor` |
| `nudge_final_answer.md` | Nudge LLM toward final response | Context assembly |
| `nudge_malformed_fallback.md` | Recovery from malformed LLM output | `TurnRunner` |
| `plan.md` | Planning — numbered step plan | Context assembly |
| `progress.md` | Mid-loop reflection — assess progress | Context assembly |
| `reasoning.md` | Structured pre-action reasoning protocol | `ContextBuilder` system prompt |
| `recovery.md` | Guardrail recovery instructions | `GuardrailChain` |
| `reflect.md` | Post-tool reflection — evaluate results | Context assembly |
| `revision_request.md` | Request revision of agent output | `TurnRunner` |
| `security_advisory.md` | Security constraint reminders | `ContextBuilder` system prompt |
| `self_check.md` | Configurable self-check pass | `TurnRunner` self-check |
| `skills_header.md` | Skills context header | `ContextBuilder` |
| `slide_analysis.md` | Slide/image analysis instructions | Skill-specific |
| `summary_system.md` | Summary generation system prompt | `summarize_and_compress()` |
| `tool_guide.md` | Purpose-driven tool selection guidance | `ContextBuilder` system prompt |
| `unavailable_tools.md` | Message when tools are unavailable | `TurnRunner` |
| `verification_required.md` | Verification pass instructions | `TurnRunner` verification |

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
