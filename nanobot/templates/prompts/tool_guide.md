# Tool Selection Guide

Match your INTENT to the right tool. Do not select by name similarity.

| Your intent | Tool | Anti-pattern |
|---|---|---|
| Find files/folders by name or code | `list_dir` | Do NOT use search — it only searches content |
| Search text inside files | `exec` with grep/search | Do NOT use this for name-based lookups |
| Read a known file | `read_file` | Do NOT guess paths — list the directory first |
| Explore unknown structure | `list_dir` first, then `read_file` | Do NOT jump to search without knowing the structure |
| Run a skill command | `exec` | Consult the skill's instructions for which command fits your intent |
| Modify a file | `write_file` or `edit_file` | Always `read_file` first to confirm current content |

## When a Skill Is Loaded

Skills provide specialized commands. But they are ADDITIONS to your
base tools, not REPLACEMENTS. If a skill command fails or returns
nothing, your base tools still work.

Read the skill's decision guide (if present) to choose the right
command for your intent. Do not default to "search" for every
lookup task.
