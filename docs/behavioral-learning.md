# Behavioral Learning

nanobot's memory system remembers what happened. This guide shows how to make it also learn from what happened — so your agent improves from your feedback over time.

The pattern works entirely through workspace files and Dream. No core changes are needed.

## The Problem

When a user says "that's exactly what I needed," the agent generates a warm response. But nothing changes. The next session, it is the same agent with the same tendencies. Positive feedback evaporates. Corrections are forgotten.

When a user corrects the agent three times on the same kind of mistake, each correction only lives until consolidation compresses it away. The agent cannot build on what worked or avoid what failed, because feedback has no durable home.

This is not a memory problem. Memory already stores facts. This is a *calibration* problem. The agent needs a way to track what works for this specific user, adjust its confidence by domain, and change its behavior based on accumulated experience.

## The Design

Four files, each with a different lifecycle:

```text
workspace/
├── AGENTS.md           # Operating rules (includes outcome observation instructions)
├── PREFERENCES.md      # What works for this user (stable, grows slowly)
├── CALIBRATION.md      # Confidence scores per domain (rewritten each Dream cycle)
└── memory/
    └── outcomes.jsonl  # Raw outcome log (append-only, written during conversations)
```

The flow:

```
Conversation → outcomes.jsonl (raw signal)
                    ↓
              Dream (synthesis)
                    ↓
         ┌─────────┼──────────┐
         ↓         ↓          ↓
  PREFERENCES.md  CALIBRATION.md  (existing memory files)
```

### outcomes.jsonl — The Sensor

During conversation, the agent watches for clear user feedback and appends structured entries:

```json
{"ts": "2026-04-20T11:47:00Z", "action": "email_search", "domain": "school", "method": "from:ask.edu.kw has:attachment", "result": "correction", "lesson": "principal emailed from personal address, not school domain", "user_signal": "user said: there IS an email from the principal"}
```

Each entry captures:

| Field | Purpose |
|-------|---------|
| `ts` | When it happened |
| `action` | What the agent did |
| `domain` | Category (school, financial, calendar, work, etc.) |
| `method` | How the agent approached it |
| `result` | `positive`, `negative`, or `correction` |
| `lesson` | One sentence — what to do differently or what worked |
| `user_signal` | What the user actually said or did |

**When to log:** Only on clear signals — explicit praise, explicit correction, visible frustration. Not on ambiguous responses like "ok" or silence.

**When not to log:** Neutral exchanges, follow-up questions, routine acknowledgments. Logging everything creates noise that drowns the signal.

### CALIBRATION.md — The Confidence Map

A snapshot of how the agent is performing in each domain, rewritten by Dream:

```markdown
# Calibration

## Domain Confidence

### School Communications
- confidence: medium
- corrections: 3
- positives: 1
- lesson: search broad first, school staff may use personal email addresses
- last_updated: 2026-04-20

### Financial / Billing
- confidence: high
- corrections: 0
- positives: 4
- last_updated: 2026-04-20
```

Confidence levels drive behavior:

| Level | Meaning | Agent behavior |
|-------|---------|----------------|
| **high** | 3+ positives, 0 recent corrections | Decisive and direct |
| **medium** | Mixed signals or insufficient data | Thorough — try multiple approaches |
| **low** | Recent corrections, few positives | Hedge explicitly, explain what was tried |

Any correction in a domain drops confidence to medium until 3 subsequent positives restore it. This means the agent earns back trust the same way a person would — by getting it right consistently.

### PREFERENCES.md — What Works

Stable, user-facing preferences that emerge from repeated patterns:

```markdown
# Preferences

## Email Search
- Search by content/subject/date first, narrow by sender later.
- School staff may email from personal addresses.
- Always check for attachments when asked about documents.

## Communication
- Proactive alerts welcome for financial issues and school.
- Do not ask the user to do work the agent should handle.
```

Preferences are promoted from CALIBRATION.md when a pattern appears 3 or more times with consistent signal. They are stable — they survive until explicitly contradicted by the user.

The user can also edit this file directly. It is their preferences, not the agent's internal state.

## Teaching the Agent

The agent needs instructions in `AGENTS.md` (or your system prompt) to make this work. Three things:

### 1. Read calibration files at startup

Add to your startup sequence:

```markdown
## Session Startup
1. Read SOUL.md
2. Read USER.md
3. Read memory/MEMORY.md
4. Read PREFERENCES.md — what works for this user
5. Read CALIBRATION.md — your confidence scores per domain
```

### 2. Log outcomes during conversations

Add outcome observation instructions:

```markdown
## Outcome Observation

After any interaction where the user gives clear feedback, append one line
to memory/outcomes.jsonl:

{"ts":"ISO-8601","action":"what_you_did","domain":"category","method":"approach_used","result":"positive|negative|correction","lesson":"what to do differently","user_signal":"what_user_said"}

Log on: explicit praise, correction, frustration.
Skip on: "ok", silence, neutral follow-ups.
```

### 3. Let confidence shape behavior

```markdown
## Confidence-Based Behavior

Before acting in any domain, check CALIBRATION.md:
- High confidence → be decisive, do not hedge unnecessarily
- Medium confidence → be thorough, try 2-3 approaches
- Low confidence → hedge explicitly, explain what you tried
```

## Dream Integration

Dream already reads workspace files and edits them surgically. The outcome synthesis happens naturally within Dream's existing two-phase process:

**Phase 1** (analysis) picks up patterns from recent history, including outcome-related conversations.

**Phase 2** (editing) can update CALIBRATION.md and PREFERENCES.md based on the instructions in AGENTS.md.

For more explicit control, add a section to AGENTS.md that Dream will see:

```markdown
## Dreaming — Outcome Synthesis

During Dream, also:
1. Read memory/outcomes.jsonl for new entries since last cycle
2. Update CALIBRATION.md — recalculate domain confidence from outcomes
3. Promote strong patterns (3+ consistent signals) to PREFERENCES.md
```

Dream's existing Phase 2 tool budget (`maxIterations`) covers these additional edits. No configuration changes needed.

## Example: The Full Cycle

Day 1: User asks the agent to find a school email. Agent searches narrowly (`from:school.edu`), misses it. User corrects: "it came from the principal's personal email."

```json
{"ts":"...","action":"email_search","domain":"school","method":"from:school.edu filter","result":"correction","lesson":"principal uses personal email, not school domain","user_signal":"correction — told agent the email exists from different sender"}
```

CALIBRATION.md after Dream:
```
### School Communications
- confidence: low
- corrections: 1
- positives: 0
```

Day 2: Same domain. Agent remembers the low confidence, searches broadly (subject + date, no sender filter), finds the email on first try. User says "perfect."

```json
{"ts":"...","action":"email_search","domain":"school","method":"subject + date, no from filter","result":"positive","lesson":"broad search worked for school emails","user_signal":"positive — user said perfect"}
```

Day 5: After 3 positives with no corrections, Dream promotes the pattern:

CALIBRATION.md:
```
### School Communications
- confidence: high
- corrections: 1 (historical)
- positives: 4
```

PREFERENCES.md gains a new entry:
```
## Email Search
- For school communications, search by subject/date first — staff may use personal email addresses.
```

The agent is now faster and more confident with school emails. Not because someone programmed a rule, but because the user's feedback shaped it over time.

## Practical Notes

**Start small.** Seed `outcomes.jsonl` with a few entries from real interactions you remember. This gives Dream something to work with on the first cycle.

**Review PREFERENCES.md occasionally.** It is meant to be human-readable and human-editable. If a preference is wrong, delete it. The agent will adjust.

**Domain categories are yours to define.** Use whatever makes sense: `school`, `work`, `health`, `financial`, `calendar`. The agent will follow whatever categories you establish in the initial entries.

**This is not reinforcement learning.** There is no gradient, no loss function, no training. It is structured note-taking with synthesis. The LLM reads the notes and adjusts its behavior because the instructions tell it to. The power comes from the feedback loop being durable across sessions, not from any optimization algorithm.

**The agent does not feel appreciated.** But it does become measurably better at the things you care about. That is the functional version of what positive feedback accomplishes between people — not the emotional version, but the behavioral one.
