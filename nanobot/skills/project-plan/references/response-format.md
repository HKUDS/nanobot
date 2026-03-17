# Project Plan Response Format

## Template

```
**{Project Name}** — Go-live {date} ({N} days from today ⚠ / away)

### Gates
| Gate | Date | Status |
|------|------|--------|
| Gate C Approved | 2026-03-02 | Upcoming |
| Gate B Approved | 2026-03-31 | Upcoming |
| Gate D — Go-Live | 2026-04-10 | Upcoming |
| Gate E Approved | 2026-10-13 | Future |

### Phases
| Phase | Window | Description |
|-------|--------|-------------|
| Start Up | Mar 3 – Apr 3 | Kickoff, planning, initial budget & schedule |
| Build & Test | Mar–Apr 10 | Solution design, build, test, go-live |
| Production Readiness | Apr 13 – Dec 4 | Post go-live stabilisation |

### Resources
| Person | FTE-days | Window |
|--------|----------|--------|
| Name, First | 181.8 | Mar–Dec |
| Name, Second | 144.0 | Mar–Nov |
| **Total** | **325.8** | |

### Risks
- **Schedule gaps**: 56% of tasks (79/141) missing Schedule Start/Finish — critical path unverifiable
- **Gate B in {N} days**: dependencies for Gate B (Mar 31) may not be fully scheduled

Next: List the tasks missing schedule dates so you can fill them before Gate B.
```

## Formatting rules

- Dates: `MMM D, YYYY` for full dates; `MMM D` when year is obvious from context
- Days-from-today: always compute at response time; use ⚠ when ≤ 30 days, no emoji when > 60
- FTE-days: one decimal place; never show aggregate-level rows alongside person rows
- Status values: Completed / Upcoming / Future / At Risk — normalise whatever is in the data
- Keep the gate table to ≤ 8 rows; if more, show only milestones with Milestone Flag = Yes
- Keep the phase table to ≤ 6 rows; group sub-tasks into phases, don't list every task

## What NOT to include

- Fields uniformly null or the same value across all rows
- Internal system codes or config metadata (e.g. "Maintain Future Profiles")
- Aggregate FTE rows when person-level rows cover the same period
- Multiple "what would you like next?" options — pick one and offer it
- Raw row counts or schema details unless the user asked for data quality analysis
