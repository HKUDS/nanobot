---
name: project-plan
description: >
  Analyze, summarize, and answer questions about project plans uploaded as Excel or CSV files.
  Use when the user uploads a spreadsheet that contains project management data — tasks, milestones,
  schedule dates, gates (A/B/C/D/E), WBS codes, resource allocations, durations, or status fields.
  Triggers on phrases like "summarize this project plan", "what is the status of this project",
  "when is go-live", "show me the milestones", "who is working on this", "how many FTE days",
  or any question about a file that has columns named Schedule Start, Schedule Finish, Milestone,
  Gate, Duration, Status, WBS, or similar project scheduling terminology.
triggers:
  - project plan
  - summarize project
  - project summary
  - project status
  - when is go-live
  - go live date
  - show milestones
  - milestone summary
  - gate review
  - gate approved
  - schedule plan
  - fte days
  - resource plan
  - wbs
  - project schedule
---

# Project Plan Skill

## Response structure — always in this order

1. **One-line headline**: project name, go-live date, and days-from-today urgency
2. **Gate / milestone table**: compact, sorted by date
3. **Phase summary**: 3–5 phases with date range and plain-language description
4. **Resources**: person-level effort only (see deduplication rule below)
5. **Data quality risks**: one line per gap, only if actionable
6. **One next-action offer**: a single concrete recommendation (not a menu)

See [references/response-format.md](references/response-format.md) for the exact output template.

## Rules

### Lead with urgency
- Always compute days from today to the nearest future milestone/go-live and put it in the headline
- If go-live is within 60 days, flag it prominently

### Deduplicate FTE rows
- When both aggregate rows (e.g. "Gate D Resource Assignments") and person-named rows exist
  covering the same date range, **use person-level rows only** for effort totals
- Never present an aggregate-sum FTE number alongside person-level numbers without resolving
  which is canonical — pick person-level and state it clearly

### Drop noise
- Never mention fields that are uniformly the same value across all rows (e.g. "Maintain Future Profiles")
- Never surface internal system metadata that the user did not ask about

### Data quality — be selective
- Only report missing-data gaps that block a specific answer the user needs
- One line per gap: `"56% of tasks missing Schedule Start/Finish — critical path unverifiable"`
- Do not enumerate every null cell

### One call to action
- End with a single concrete next-step offer, not a numbered menu of options
- Choose the most valuable next step given the context (usually: fill missing dates before the
  next gate, or produce a milestone CSV, or identify the critical path)

## Tool workflow

1. Call `read_spreadsheet` to load the file and get the cache_key + column summary
2. Call `query_data` with targeted SQL to extract:
   - Milestones (where Milestone Flag = 'Yes' or similar)
   - Person-level allocation rows (where Name contains an actual person's name, not a phase label)
   - Tasks missing Schedule Start or Finish (for data quality count)
3. Compute today-relative dates before composing the response
4. Format response per the template in references/response-format.md
