---
name: knowledge
description: Manage the personal knowledge base — create, update, and cross-reference knowledge entries.
metadata: {"nanobot":{"emoji":"🧠"}}
---

# Knowledge Base Management

The knowledge base is a structured collection of files at `workspace/knowledge/`.
It is the agent's long-term, topic-organized memory — complementing `MEMORY.md` (quick-access facts) and `HISTORY.md` (grep-searchable event log).

## Structure

```
workspace/knowledge/
    INDEX.md          <- master index, loaded every turn in system prompt
    TEMPLATE.md       <- reference template for new entries
    topics/           <- subjects discussed in depth (includes concepts, ideas, frameworks)
    people/           <- individuals with context and relationship
    decisions/        <- choices made with rationale, insights, and lessons learned
    facts/            <- concrete, stable information worth remembering
    preferences/      <- user preferences for tools, styles, approaches
    projects/         <- ongoing work spanning multiple entities
    references/       <- books, articles, laws, theorems, films, music, art, websites
```

## INDEX.md

The index is loaded into the system prompt every turn. It must stay lightweight — one line per entry.

Format:
```markdown
## Topics
- docker: Container setup, compose configs, deployment patterns
- authentication: OAuth2 flow, token management

## People
- alice: Frontend lead, dashboard project

## Decisions
- 2024-03-use-litellm: Chose LiteLLM for multi-provider support
```

Rules:
- One line per entry: `- filename: Brief summary`
- Grouped by type (matching subdirectory names)
- Keep under 100 lines total
- If growing too large, consolidate related entries into broader files

## Entity File Format

Every knowledge file uses YAML frontmatter followed by markdown content:

```markdown
---
type: topic
created: 2025-01-15
updated: 2025-02-10
related: [people/alice, decisions/2024-03-use-litellm]
tags: [architecture, backend]
---
# Authentication System

## Summary
OAuth2-based auth with JWT tokens...

## Details
Full content here.

## Evolution
- 2025-01-15: Initial design discussion
- 2025-02-10: Switched from session cookies to JWT
```

### Frontmatter Fields
- `type`: One of: topic, person, decision, fact, preference, project, reference
- `created`: Date of creation (YYYY-MM-DD)
- `updated`: Date of last meaningful update (YYYY-MM-DD)
- `related`: List of paths to related entries (relative to knowledge/)
- `tags`: Freeform tags for additional categorization

### Cross-References
The `related` field links entries together. When exploring a topic, follow related links to build fuller context by reading those files.

## When to Create or Update Entries

Create entries when conversations involve:
- **Topics**: A subject discussed in depth or repeatedly (includes concepts, ideas, frameworks)
- **People**: A person mentioned with meaningful context
- **Decisions**: A choice made with reasoning, an insight, or a lesson learned
- **Facts**: Concrete, stable information worth retaining (configurations, setups, accounts)
- **Preferences**: A user preference expressed (coding style, communication, tools)
- **Projects**: Ongoing work that spans multiple topics, people, or decisions
- **References**: A book, article, law, theorem, film, piece of music, artwork, or notable website

Update entries when:
- New information adds to or changes existing knowledge
- A decision is revisited or reversed
- Related entries are created that should be cross-referenced

## How to Create an Entry

1. Read `INDEX.md` to check if an entry already exists
2. If not, choose the appropriate subdirectory
3. Pick a descriptive kebab-case filename: `docker-compose-setup.md`
4. Copy the structure from `TEMPLATE.md`
5. Fill in frontmatter and content
6. Add a one-line summary to `INDEX.md` under the correct section
7. Check if existing entries should add a `related` link to the new entry

## How to Update an Entry

1. Read the existing file
2. Update content and set `updated` date in frontmatter
3. Add a dated line to the Evolution section if the change is significant
4. Add any new `related` links
5. Update the summary in `INDEX.md` if it changed

## How to Use the Knowledge Base

When answering a question or working on a task:
1. Scan `INDEX.md` (already in context) for relevant entries
2. Read the full file for any relevant entry via `read_file`
3. Follow `related` links if you need broader context
4. After the task, consider whether new knowledge should be captured
