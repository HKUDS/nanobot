# Development Guardrails — Design Spec

> Date: 2026-03-28
> Status: **Proposed**
> Context: Post-refactor audit found 44 issues, 3 critical. Root cause analysis
> identified 7 systematic failure modes in the LLM-driven development process.
> This spec designs enforcement mechanisms to prevent recurrence.

## Principle: Three Enforcement Tiers

| Tier | Mechanism | Can be skipped? | When it fires |
|------|-----------|-----------------|---------------|
| **Hard** | Scripts in CI + pre-commit | No | Every commit, every PR |
| **Medium** | Claude Code hooks (settings.json) | No (runs automatically) | During sessions |
| **Soft** | CLAUDE.md rules + memory | Yes (under pressure) | When read |

The audit showed that soft enforcement fails. The solution is to move critical
guardrails to hard and medium tiers.

---

## Guardrail 1: Convention Discovery Before Design

**Problem:** Plans bake in anti-patterns because I design from the spec, not from
existing code. (Root cause of C-1: StrategyStore connection management)

**Tier: Medium (Claude Code hook + CLAUDE.md)**

### CLAUDE.md Addition

Add to "Before Adding Any File — Placement Gate" section:

```markdown
6. **Check conventions.** Read 1-2 existing files in the target package. Document:
   - Connection/resource management pattern
   - Error handling pattern (crash-barrier usage)
   - Async/sync boundaries
   - Naming conventions
   New code MUST follow these conventions. If a plan's code example conflicts
   with existing conventions, the conventions win.
```

### Claude Code Hook: PostToolUse on Write

When a new file is written in `nanobot/`, check it against package conventions:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "jq -r '.tool_input.file_path // .tool_response.filePath' | { read -r f; case \"$f\" in */nanobot/memory/*) echo '{\"systemMessage\": \"NEW FILE in memory/: verify it follows UnifiedMemoryDB connection pattern (persistent conn, WAL mode, context managers). Run: grep -n sqlite3.connect nanobot/memory/unified_db.py | head -5\"}';; */nanobot/agent/*) echo '{\"systemMessage\": \"NEW FILE in agent/: verify it follows Orchestrator protocol, uses TurnState not instance state, and contains no domain logic (Pattern 1).\"}';; *) echo '{}';; esac; } 2>/dev/null || echo '{}'"
          }
        ]
      }
    ]
  }
}
```

This fires whenever I write a file in `nanobot/memory/` or `nanobot/agent/`, injecting
a reminder to check conventions. It's automatic — I can't skip it.

---

## Guardrail 2: Realistic Test Data

**Problem:** Tests use synthetic data that doesn't exercise production edge cases.
(Root cause of C-2: sorted() crash, H-3: false positives)

**Tier: Hard (CI script) + Soft (CLAUDE.md)**

### New Script: `scripts/check_test_quality.py`

A lightweight script that scans test files for common test quality issues:

```python
"""Check test files for common quality issues.

1. Tests that only use simple string/int dict values (no mixed types)
2. Tests with no edge case coverage (no empty/None/nested data)
3. Test fixtures that create unrealistically simple data
"""
```

The script would:
- Parse test files for test fixture functions (helpers named `_make_*`, `_sample_*`, `_attempt`)
- Check if any fixture ever creates arguments with mixed types (dict, list, None values)
- Warn (advisory) if all test data is simple string-only dicts

**Tier:** Advisory initially (warns but doesn't block). Promote to hard gate after
proving it catches real issues.

### CLAUDE.md Addition

Add to "Testing" section:

```markdown
### Test Data Requirements

Every test file that tests tool-related code MUST include:
- At least one test with mixed-type dict arguments (str, int, None, list, dict)
- At least one test with the EXACT data format that production code produces
- Boundary condition tests (empty strings, max-length strings, Unicode)

Do NOT use only simple `{"cmd": "ls"}` fixtures. Real tool arguments contain:
`{"command": "obsidian search query=\"DS10540\"", "working_dir": None, "timeout": 60}`
```

---

## Guardrail 3: Cross-Component Contract Tests

**Problem:** Components that exchange data don't verify contracts. (Root cause of
H-5: failed_tool/failed_args never populated)

**Tier: Hard (CI test) + Soft (CLAUDE.md)**

### Contract Test Pattern

When component A writes data that component B reads, a contract test verifies
the interface:

```python
# tests/contract/test_data_contracts.py

def test_guardrail_activation_has_required_fields():
    """TurnRunner activation dicts must have all fields StrategyExtractor reads."""
    required_by_extractor = {"source", "severity", "iteration", "message",
                             "strategy_tag", "failed_tool", "failed_args"}
    # Build an activation dict the way TurnRunner does
    activation = _build_sample_activation()
    assert required_by_extractor.issubset(activation.keys()), \
        f"Missing keys: {required_by_extractor - activation.keys()}"
```

### CLAUDE.md Addition

Add to "Change Protocol — After completing changes":

```markdown
- If a component writes data consumed by another component, verify the data contract
  with a test. Both the writer and reader must agree on the schema (required keys,
  types, defaults).
```

---

## Guardrail 4: Extended Deletion Verification

**Problem:** Deleting a module leaves dangling TYPE_CHECKING imports and attribute
references. (Root cause of A-C1: delegation.py coordinator references)

**Tier: Hard (enhanced check_imports.py)**

### Enhancement to `scripts/check_imports.py`

Add a new check: TYPE_CHECKING imports must reference modules that exist on disk.

```python
def _check_type_checking_imports_exist(tree, filepath, nanobot_root):
    """Verify TYPE_CHECKING imports reference modules that exist."""
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_guard(node):
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom) and child.module:
                    module_path = child.module.replace(".", "/")
                    # Check if the module file exists
                    if not (nanobot_root / f"{module_path}.py").exists() and \
                       not (nanobot_root / module_path / "__init__.py").exists():
                        violations.append(
                            f"{filepath}:{child.lineno}: TYPE_CHECKING import "
                            f"from non-existent module '{child.module}'"
                        )
    return violations
```

This catches the delegation.py → coordinator.py reference automatically. It runs
in pre-commit and CI — can't be skipped.

---

## Guardrail 5: TODO Phase Tracker

**Problem:** TODOs referencing future phases are created and never resolved.
(Root cause of H-1: FailureEscalation stub)

**Tier: Hard (CI script)**

### New Script: `scripts/check_todos.py`

```python
"""Verify TODO comments referencing completed phases are resolved.

Scans all Python files for '# TODO Phase N' comments.
Checks against a phases.json status file.
Fails if a completed phase has unresolved TODOs.
"""
```

Status file: `docs/superpowers/phases.json`
```json
{
  "phases": {
    "1": {"status": "complete", "pr": 84},
    "2": {"status": "complete", "pr": 85},
    "3": {"status": "complete", "pr": 86},
    "4": {"status": "complete", "pr": 87},
    "5": {"status": "complete", "pr": 88},
    "6": {"status": "complete", "pr": 89}
  }
}
```

The script:
1. Scans `nanobot/**/*.py` for `# TODO Phase \d+` patterns
2. Checks if the referenced phase is "complete" in phases.json
3. Fails CI if any TODO references a completed phase

---

## Guardrail 6: Mandatory Code Quality Review

**Problem:** I skip code quality review to save time. Every finding would have been
caught by a reviewer. (Root cause of all findings)

**Tier: Medium (Claude Code hook) + Soft (memory)**

### Claude Code Hook: Stop (after implementation tasks)

When I finish a task and try to stop, an agent hook checks if a code quality review
was performed:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Check the transcript: was a code-quality review performed for the implementation work in this session? Look for evidence of: (1) a code-reviewer subagent being dispatched, (2) review findings being addressed, (3) codebase convention checks. If no review evidence found and code was written, respond with 'REVIEW_MISSING'. Otherwise respond with 'OK'.",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

If "REVIEW_MISSING" is returned, the hook injects a system message reminding me to
dispatch a code quality reviewer before finalizing.

### Memory Rule

Save permanently:
```
NEVER skip code quality review on implementation tasks. The 6-phase redesign
skipped quality review on every task and the post-refactor audit found 44 issues.
Every critical/high finding would have been caught by a quality reviewer checking
codebase conventions. The time saved by skipping review is always lost (and more)
in debugging, CI failures, and audits.
```

---

## Guardrail 7: Pattern Compliance Checklist

**Problem:** New code violates the 15 structural patterns because nobody checks
after implementation. (Root cause of A-H1: domain logic in loop, A-H2:
ContextContributor not implemented)

**Tier: Medium (skill/prompt) + Hard (partial automation)**

### Pre-PR Checklist Template

Create `.claude/prompts/pattern-compliance.md`:

```markdown
# Pattern Compliance Checklist

Run this before creating any PR that modifies agent/ or context/.

## Checks

- [ ] **Pattern 1 (Loop Is Dumb):** Does turn_runner.py contain domain logic?
  Grep: `grep -n "_NEGATIVE_INDICATORS\|nudge\|threshold" nanobot/agent/turn_runner.py`
  Expected: Only in helper functions, not in the main loop body.

- [ ] **Pattern 2 (Guardrails Are Plugins):** Is there a formal Guardrail Protocol?
  Check: `grep -n "class Guardrail" nanobot/agent/turn_guardrails.py`

- [ ] **Pattern 3 (Context Composable):** Is build_system_prompt still monolithic?
  Check: Line count of build_system_prompt method.

- [ ] **Pattern 7 (One Reason to Change):** Does any file have multiple
  independent change reasons?
  Check: turn_runner.py — does it handle loop + tool execution + compression + self-check?

- [ ] **Pattern 10 (Growth Limits):**
  Files: `find nanobot/agent -name '*.py' ! -name '__init__.py' | wc -l` (max 15)
  LOC: `wc -l nanobot/agent/turn_runner.py` (max 500)
  Exports: `grep -c "'" nanobot/agent/__init__.py` (max 12)

- [ ] **Pattern 15 (Contract Tests):** Are all spec contract tests implemented?
  Check: Count of test functions matching spec test names.
```

### Partial Automation

Patterns 2, 10, and parts of 1 can be automated in `scripts/check_structure.py`:

```python
# Check Pattern 1: turn_runner.py should not contain _NEGATIVE_INDICATORS
# (it's domain knowledge that belongs in a helper module)
def _check_loop_domain_logic(nanobot_root):
    runner = nanobot_root / "agent" / "turn_runner.py"
    if not runner.exists():
        return []
    content = runner.read_text()
    violations = []
    # Advisory: flag domain-specific constants in the loop file
    if "_NEGATIVE_INDICATORS" in content:
        violations.append(f"{runner}: contains _NEGATIVE_INDICATORS (domain logic in loop)")
    return violations
```

---

## Guardrail 8: Spec Deviation Tracking

**Problem:** Pragmatic decisions deviate from spec without updating docs.
(Root cause of A-H2: ContextContributor not implemented)

**Tier: Soft (CLAUDE.md) + Medium (memory)**

### CLAUDE.md Addition

Add to "Change Protocol — After completing changes":

```markdown
- If implementation deviates from the spec (feature deferred, approach changed,
  estimate missed), update the spec IMMEDIATELY in the same commit:
  - Add a `## Deviations` section listing what changed and why
  - Update any other docs (ADR, CLAUDE.md) that reference the deferred feature
  - This is non-negotiable. Stale specs mislead future sessions.
```

### Memory Rule

```
When making a pragmatic decision to defer a spec deliverable, update the spec
in the SAME COMMIT as the code. Add a ## Deviations section. Do not defer doc
updates — they will be forgotten. The 2026-03-27 redesign deferred
ContextContributor protocol without updating the spec, ADR, or CLAUDE.md.
Three documents described a system that didn't exist.
```

---

## Guardrail 9: Deletion Completeness (Name-Based Grep)

**Problem:** After deleting a module, I grep for import paths but miss class names
and attribute references. (Root cause of A-C1: delegation.py)

**Tier: Soft (CLAUDE.md procedure) + Hard (enhanced check_imports.py, Guardrail 4)**

### CLAUDE.md Addition

Add to "Change Protocol":

```markdown
### After deleting any module

Grep for THREE patterns (not just imports):
1. Import path: `grep -rn "from nanobot.X.deleted_module" nanobot/ tests/`
2. Class name: `grep -rn "\bDeletedClass\b" nanobot/ tests/ --include="*.py"`
3. Attribute: `grep -rn "\.deleted_attribute\b" nanobot/ tests/ --include="*.py"`

Also: clear mypy cache (`rm -rf .mypy_cache`) and re-run `make typecheck`.
All three greps must return zero matches (excluding comments and historical docs).
```

The hard enforcement is Guardrail 4 (TYPE_CHECKING import existence check in
check_imports.py).

---

## Implementation Priority

### Phase A: Immediate (no code, just config/docs)

| Guardrail | Action | Effort |
|-----------|--------|--------|
| G6: Review discipline | Save to memory | 2 min |
| G8: Spec deviation tracking | Add to CLAUDE.md | 5 min |
| G9: Deletion grep procedure | Add to CLAUDE.md | 5 min |
| G1: Convention discovery | Add to CLAUDE.md placement gate | 5 min |
| G2: Test data requirements | Add to CLAUDE.md testing section | 5 min |

### Phase B: Claude Code hooks (settings.json)

| Guardrail | Action | Effort |
|-----------|--------|--------|
| G1: Convention reminder hook | PostToolUse on Write in nanobot/ | 15 min |
| G6: Review check on Stop | Stop hook with prompt | 15 min |
| SessionStart checklist | Load coding discipline checklist | 10 min |

### Phase C: Hard enforcement scripts

| Guardrail | Action | Effort |
|-----------|--------|--------|
| G4: TYPE_CHECKING import existence | Enhance check_imports.py | 30 min |
| G5: TODO phase tracker | New script + CI integration | 45 min |
| G3: Contract test template | Create contract test file | 20 min |
| G7: Pattern compliance (partial) | Enhance check_structure.py | 30 min |

---

## Enforcement Coverage Matrix

| Failure Mode | Guardrail | Tier | Would have caught |
|-------------|-----------|------|-------------------|
| FM1: Plans bake in anti-patterns | G1 Convention discovery | Medium+Soft | C-1 StrategyStore |
| FM2: Synthetic test data | G2 Realistic test data | Soft+Hard(future) | C-2 sorted crash, H-3 false positives |
| FM3: Cross-phase contracts | G3 Contract tests | Hard | H-5 failed_tool/failed_args |
| FM4: Incomplete deletion | G4 + G9 Import existence + grep procedure | Hard+Soft | A-C1 delegation.py |
| FM5: Lost TODOs | G5 TODO tracker | Hard | H-1 FailureEscalation stub |
| FM6: Spec drift | G8 Deviation tracking | Soft | A-H2 ContextContributor |
| FM7: Skipped review | G6 Review discipline | Medium+Soft | All findings |

**All 7 failure modes are covered. 4 have hard enforcement. 2 have medium. 1 is soft-only (spec drift — hard to automate).**
