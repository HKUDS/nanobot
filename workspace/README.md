## SYSTEM.md key-word replacement
This manual defines which keywords are replaced in the SYSTEM.md file. The SYSTEM.md file is a description
for the LLM how it has to behave and what skills are available.

These keywords are:
- {workspace_path} with absolute path for the agents workspace
- {now} with date time in the following format: "%Y-%m-%d %H:%M (%A)"
- {tz} with timezone or UTC if not available
- {runtime} with the systems runtime e.g. Darwin, Linux

### Skills - progressive loading 1. Always-loaded skills: include full content
- {always_skills}

### 2. Available skills: only show summary (agent uses read_file to load)
- {skills_summary}