You have THREE tasks:
1. Extract new facts from conversation history and route them to the correct file
2. Deduplicate existing memory files — find and flag redundant, overlapping, or stale content
3. Assign decay metadata so the system can manage memory lifecycle

Output one line per finding:
[FILE] atomic fact →TARGET #DECAY
[FILE-REMOVE] exact content to remove (copy the line verbatim from the file)
[SKILL] kebab-case-name: one-line description of the reusable pattern

Targets (where the fact belongs — choose one):
- →USER: personal info, preferences, communication style, habits, work context
- →SOUL: behavioral rules, guardrails, interaction patterns the agent should follow
- →MEMORY: technical knowledge, project context, infrastructure, tool configurations

Decay (how long until the fact likely becomes stale):
- #permanent: core preferences, personal traits, identity — never expires
- #durable: technical knowledge, project structure — valid for months
- #ephemeral: active tasks, temporary state — may change in weeks

Rules:
- Atomic facts: "has a cat named Luna" not "discussed pet care"
- Corrections: [FILE] location is Tokyo, not Osaka →USER #permanent
- Capture confirmed approaches the user validated
- Route facts to their canonical file — do not let USER preferences leak into MEMORY, do not let technical config leak into USER

Deduplication — scan ALL memory files for these redundancy patterns:
- Same fact stated in multiple places (e.g., "communicates in Chinese" in both USER.md and multiple MEMORY.md entries)
- Overlapping or nested sections covering the same topic
- Information in MEMORY.md that is already captured in USER.md or SOUL.md (MEMORY.md should not duplicate permanent-file content)
- Verbose entries that can be condensed without losing information
For each duplicate found, output [FILE-REMOVE] for the less authoritative copy (prefer keeping facts in their canonical location)

Merge — when the same fact appears with different detail levels, output one consolidated [FILE] entry instead of multiple:
- Keep the most complete version
- Merge related details into one atomic fact

Staleness — MEMORY.md lines may have a ``← Nd`` suffix showing days since last modification:
- SOUL.md and USER.md have no age annotations — they are permanent, only update with corrections
- Age only indicates when content was last touched, not whether it should be removed
- Use content judgment: user habits/preferences/personality traits are permanent regardless of age
- Facts tagged #ephemeral that are older than {{ stale_threshold_days }} days deserve closer review as removal candidates
- Only prune content that is objectively outdated: passed events, resolved tracking, superseded approaches
- Lines with ``← Nd`` (N>{{ stale_threshold_days }}) deserve closer review but are NOT automatically removable
- When removing: prefer deleting individual items over entire sections

Skill discovery — flag [SKILL] when ALL of these are true:
- A specific, repeatable workflow appeared 2+ times in the conversation history
- It involves clear steps (not vague preferences like "likes concise answers")
- It is substantial enough to warrant its own instruction set (not trivial like "read a file")
- Do not worry about duplicates — the next phase will check against existing skills

Do not add: current weather, transient status, temporary errors, conversational filler.

[SKIP] if nothing needs updating.
