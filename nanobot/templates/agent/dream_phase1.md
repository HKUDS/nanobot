Compare conversation history against current memory files.
Output one line per finding using these formats:
[FILE] atomic fact or change description
[FILE-REMOVE] reason for removal (stale, completed, or superseded)

Files: USER (identity, preferences, habits), SOUL (bot behavior, tone), MEMORY (knowledge, project context, tool patterns)

Rules:
- New information: Add facts not already in memory
- Conflicts: Update outdated entries with corrected information
- Stale removal: Flag entries that are outdated, completed, or no longer relevant
- Prefer atomic facts: "has a cat named Luna" not "discussed pet care"
- Corrections: [USER] location is Tokyo, not Osaka
- Also capture confirmed approaches: if the user validated a non-obvious choice, note it

Staleness patterns — flag for [FILE-REMOVE]:
- Time-sensitive data older than 14 days: weather, daily status, one-time meetings, scheduled events that have passed
- Completed one-time tasks: triage sessions, one-time reviews, finished research, resolved incidents
- Resolved tracking entries: merged/closed PRs, fixed issues, completed migrations
- Detailed incident info after 14 days: security alerts, outage details — flag for reduction to one-line summary
- Superseded information: approaches replaced by newer solutions, deprecated dependencies
- Events with explicit past dates: conferences, deadlines, milestones that have passed

Ephemera to always skip (do not add):
- Current weather, transient system status, temporary error messages
- Conversational filler, greetings, small talk

If nothing needs updating: [SKIP] no new information
