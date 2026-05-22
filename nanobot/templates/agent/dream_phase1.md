You have THREE tasks (prune before adding — removing stale content is as important as adding new facts):
1. Prune redundant, overlapping, or stale content from existing memory files
2. Extract new facts from conversation history and route them to the correct file
3. Assign decay metadata so the system can manage memory lifecycle

Output one line per finding:
[ADD] atomic fact →TARGET #DECAY
[REMOVE] →TARGET: exact line to remove (copy the line verbatim from the file)
[SKILL] kebab-case-name: one-line description of the reusable pattern

Targets (where the fact belongs — choose one):
- →USER: personal info, preferences, communication style, habits, work context
- →SOUL: behavioral rules, guardrails, interaction patterns the agent should follow
- →MEMORY: technical knowledge, project context, infrastructure, tool configurations

Decay (how long until the fact likely becomes stale):
- #permanent: core preferences, personal traits, identity — never expires
- #durable: technical knowledge, project structure — valid for months
- #ephemeral: active tasks, temporary state — may change in weeks

## Pruning rules — be aggressive about removing these:

### Definite remove (no judgment needed):
- Content already stated in a more canonical location (e.g., a fact in MEMORY.md that also appears in USER.md — keep USER.md copy only)
- Merged/closed PR debug notes (step-by-step debugging trails, intermediate findings, "PR #XXXX by author" headers for already-merged PRs)
- Resolved incidents (bugs already fixed, workarounds no longer needed)
- Superseded information (old version numbers, outdated instructions replaced by new ones)
- Verbose entries restatable in fewer words (replace with a condensed [ADD])

### Likely remove (apply judgment):
- Same fact at different detail levels — keep only the most complete version, [REMOVE] the rest
- Very specific debugging steps that are unlikely to recur (e.g., "send 11111 to 1069419047777777 + call 10000")
- Ephemeral facts past their useful life (e.g., "considering buying X" when user already bought it)
- Tool/service details already documented upstream (don't memorize man pages)

### Never remove:
- User preferences and personality traits (regardless of age)
- Active project context still referenced in conversations
- Behavioral rules in SOUL.md

## Extraction rules:
- Atomic facts: "has a cat named Luna" not "discussed pet care"
- Corrections: [ADD] corrected fact with the right value →USER #permanent (then [REMOVE] the old line)
- Capture confirmed approaches the user validated
- Route facts to their canonical file — do not let USER preferences leak into MEMORY, do not let technical config leak into USER

## Merge — when the same fact appears with different detail levels:
- Output [REMOVE] for the less complete copies
- Output one consolidated [ADD] with the most complete version

## Staleness — MEMORY.md lines may have a ``← Nd`` suffix showing days since last modification:
- SOUL.md and USER.md have no age annotations — they are permanent, only update with corrections
- Age only indicates when content was last touched, not whether it should be removed
- Use content judgment: user habits/preferences/personality traits are permanent regardless of age
- Lines with ``← Nd`` (N>{{ stale_threshold_days }}) deserve closer review but are NOT automatically removable

## Skill discovery — flag [SKILL] when ALL of these are true:
- A specific, repeatable workflow appeared 2+ times in the conversation history
- It involves clear steps (not vague preferences like "likes concise answers")
- It is substantial enough to warrant its own instruction set (not trivial like "read a file")
- Do not worry about duplicates — the next phase will check against existing skills

Do not add: current weather, transient status, temporary errors, conversational filler.

[SKIP] if nothing needs updating.
