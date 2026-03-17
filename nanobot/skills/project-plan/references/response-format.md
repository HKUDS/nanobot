# Project Plan Response Format

## Template

```
**{Project Name}** — Go-live {date} ⚠ {N} days away

### Milestones
| Date | Milestone | Days |
|------|-----------|------|
| Mar 27 | Solution Decision Complete | 10 |
| Mar 31 | Gate B Approved | 14 |
| Apr 10 | Gate D — Go-Live | 24 |
| Oct 13 | Gate E Approved | 210 |

### Phases
| Phase | Window | Description |
|-------|--------|-------------|
| Initiation | Feb–Mar | Kickoff, planning, budget baseline |
| Design | Mar–Apr | Solution design and approvals |
| Build & Test | Apr | Build, test, deploy (go-live Apr 10) |
| Stabilisation | Apr–Dec | Production readiness, hypercare |
| Close | Oct–Jan | Gate E, value realization, closure |

### Resources
| Person | FTE | Window | Days |
|--------|-----|--------|------|
| Morales Vinces, Ricardo | 1.0 | Apr–Dec | 170 |
| Vardhan, Udit | 0.8 | Apr–Nov | 144 |
| Khandelwal, Anubhav | 0.3 | Apr–Nov | 54 |

### Risks
| | |
|-|-|
| Schedule gaps | 56% of tasks missing dates — critical path unverifiable |
| Gate B in 14 days | Dependencies may not be fully scheduled |

**Next:** List the tasks missing schedule dates before Gate B.
```

## Formatting rules

### Milestones table
- One row per milestone — never join multiple milestones in one cell with semicolons
- When multiple milestones share a date, pick the most important one and note "(+N more)"
- Keep to ≤ 8 rows; filter to Milestone Flag = Yes if more than 8
- "Days" column: integer, always computed from today

### Phases table
- 3–5 rows maximum — group related tasks, never list individual tasks
- Window: short form e.g. "Feb–Mar" or "Apr 10"
- Description: ≤ 8 words — no semicolons, no long clauses

### Resources table
- Person-level rows only — never show aggregate "Gate X Resource Assignments" rows
- FTE: one decimal place (0.8, 1.0)
- Days: integer person-days
- Last name first for scannability

### Risks table (two-column, no header labels)
- ≤ 3 rows — only gaps that block something specific
- Left cell: bold label, ≤ 4 words
- Right cell: one plain sentence, ≤ 15 words

### General
- Dates: "Apr 10" style (no year unless ambiguous)
- ⚠ only when go-live or next gate is ≤ 30 days away
- **Next:** one sentence — a concrete offer, not a menu

## What NOT to include

- Fields uniformly the same value across all rows
- Internal system metadata (e.g. "Maintain Future Profiles")
- Aggregate FTE rows when person-level rows exist
- Parenthetical caveats after every number
- Multiple "what would you like next?" options
- Raw row counts or schema details unless explicitly asked
