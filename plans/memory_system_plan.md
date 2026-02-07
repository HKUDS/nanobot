# OpenClaw-Style Memory System for Nanobot

## Technical Implementation Plan

---

## 1. High-Level Architecture

### 1.1 Design Philosophy

The memory system extends the existing [`MemoryStore`](nanobot/agent/memory.py) class while maintaining:
- **Local-first**: All data stored locally in workspace
- **Transparency**: Human-readable file formats (Markdown, JSON)
- **Lightweight**: Minimal dependencies, < 2k lines total
- **Extensible**: Modular design for future enhancements
- **Single-user first**: Optimized for personal agent use

### 1.2 System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Nanobot Agent Loop                                │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────────────┐  │
│  │ Inbound Msg │────▶│  ContextBuilder  │────▶│  LLM Provider           │  │
│  └─────────────┘     │  ┌────────────┐  │     │                          │  │
│                      │  │MemoryModule│  │     └──────────────────────────┘  │
│                      │  └────────────┘  │                                      │
│                      └──────────────────┘                                      │
│                                    │                                            │
│                                    ▼                                            │
│  ┌─────────────┐     ┌──────────────────┐                                      │
│  │ Outbound Msg│◀────│  Tool Registry   │◀─────────────────────┐            │
│  └─────────────┘     │  ┌────────────┐  │                       │            │
│                      │  │  Tools     │  │                       │            │
│                      │  └────────────┘  │                       │            │
│                      └──────────────────┘                       │            │
│                                                                 │            │
└─────────────────────────────────────────────────────────────────│────────────┘
                                                                  │
                                                                  ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                           Memory Subsystem                                      │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                         MemoryManager                                     │  │
│  │  ┌─────────────────────────────────────────────────────────────────────┐ │  │
│  │  │                    Memory Layers                                     │ │  │
│  │  │                                                                    │ │  │
│  │  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │ │  │
│  │  │  │  Working Memory │  │ Short-Term Mem  │  │   Long-Term Memory   │  │ │  │
│  │  │  │  (In-Memory)    │  │  (Daily Notes)  │  │  (Indexed Storage)   │  │ │  │
│  │  │  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘  │ │  │
│  │  │           │                     │                     │              │ │  │
│  │  │           ▼                     ▼                     ▼              │ │  │
│  │  │  ┌─────────────────────────────────────────────────────────────────┐ │ │  │
│  │  │  │                    Skill-Specific Memory                        │ │ │  │
│  │  │  │         (Per-skill memory files in skills/{skill}/memory/)      │ │ │  │
│  │  │  └─────────────────────────────────────────────────────────────────┘ │ │  │
│  │  └─────────────────────────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                         Storage Layer                                     │  │
│  │                                                                          │  │
│  │  workspace/memory/                                                       │  │
│  │  ├── MEMORY.md           # Long-term consolidated memory               │  │
│  │  ├── index.json          # Memory index for fast lookup                │  │
│  │  ├── archives/           # Archived/deduplicated memories               │  │
│  │  ├── skills/             # Skill-specific memories                      │  │
│  │  │   └── {skill}/                                                     │  │
│  │  │       ├── memory.md                                                │  │
│  │  │       └── index.json                                               │  │
│  │  └── daily/              # Daily conversation notes                     │  │
│  │      └── YYYY-MM-DD.md                                                │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Component Overview

| Component | Responsibility | Location |
|-----------|----------------|----------|
| `MemoryManager` | Orchestrates all memory operations | `nanobot/agent/memory.py` |
| `MemoryStore` | Base class for file I/O | `nanobot/agent/memory.py` |
| `MemoryIndex` | Index management for fast lookup | `nanobot/agent/memory.py` |
| `MemoryRetriever` | Retrieval logic with scoring | `nanobot/agent/memory.py` |
| `MemoryWriter` | Automatic memory writing logic | `nanobot/agent/memory.py` |

---

## 2. Memory Layers

### 2.1 Working Memory (In-Memory)

**Purpose**: Ultra-short-term context within a single agent run.

**Characteristics**:
- Duration: Single message processing cycle
- Size: ~5-10 most recent memories
- Format: Python dict/list in memory
- Access: Direct object reference

```python
# nanobot/agent/memory.py

class WorkingMemory:
    """In-memory working memory for current processing cycle."""
    
    def __init__(self):
        self.recent_memories: list[Memory] = []
        self.current_context: dict = {}
        self.importance_threshold: float = 0.5
    
    def add(self, memory: "Memory", importance: float) -> None:
        """Add memory to working memory."""
        if importance >= self.importance_threshold:
            self.recent_memories.append(memory)
            # Keep only last 10
            self.recent_memories = self.recent_memories[-10:]
    
    def get_all(self) -> list["Memory"]:
        """Get all working memories."""
        return self.recent_memories.copy()
    
    def clear(self) -> None:
        """Clear working memory after processing."""
        self.recent_memories = []
```

### 2.2 Short-Term Memory (Daily Notes)

**Purpose**: Conversation context for current session/day.

**Existing Implementation**: Uses [`get_today_file()`](nanobot/agent/memory.py:21) and daily markdown files.

**Enhancements**:
- Structured frontmatter for metadata
- Automatic daily rotation
- Auto-pruning of old daily notes (> 30 days by default)

**File Format**:
```markdown
---
date: 2026-02-07
session: cli:user123
last_updated: 2026-02-07T21:30:00
---

# 2026-02-07

## Conversation Summary
- User discussed project timeline
- Asked about deployment process

## Action Items
- [ ] Review PR #42
- [ ] Update documentation

## Key Decisions
- Use PostgreSQL for persistence
- Deploy on Fridays only
```

### 2.3 Long-Term Memory

**Purpose**: Persistent important information across sessions.

**Structure**: Single consolidated `MEMORY.md` file with sections.

**Sections**:
```
workspace/memory/MEMORY.md
├── # Long-term Memory
├── ## User Information
│   └── Facts about the user
├── ## Preferences
│   └── User preferences learned over time
├── ## Project Context
│   └── Information about ongoing projects
├── ## Skills & Tools
│   └── Knowledge about tool usage patterns
├── ## Important Facts
│   └── High-importance persistent information
└── ## Archived (auto-generated, don't edit)
    └── Deduplicated/ancient memories
```

**Metadata Enhancement**: Add `memory_index.json` for fast lookup.

```json
// workspace/memory/index.json
{
  "version": "1.0",
  "last_updated": "2026-02-07T21:30:00",
  "memories": [
    {
      "id": "mem_001",
      "content_preview": "User prefers dark mode",
      "tags": ["preference", "ui", "user"],
      "importance": 0.8,
      "created": "2026-01-15T10:00:00",
      "updated": "2026-02-01T14:30:00",
      "section": "preferences",
      "line_range": [15, 20]
    }
  ],
  "tags": {
    "preference": ["mem_001", "mem_005"],
    "ui": ["mem_001"],
    "user": ["mem_003", "mem_007"]
  }
}
```

### 2.4 Skill-Specific Memory

**Purpose**: Per-skill knowledge that persists across sessions.

**Location**: `workspace/skills/{skill-name}/memory/`

**Structure**:
```
skills/github/
├── SKILL.md
└── memory/
    ├── context.md          # Skill-specific context
    ├── history.jsonl       # Skill usage history
    └── index.json          # Skill memory index
```

**Example Skill Memory**:
```markdown
<!-- skills/github/memory/context.md -->
# GitHub Skill Context

## Repository Patterns
- User frequently works with Python projects
- Prefers ruff for linting
- Uses conventional commits

## Common Commands
- `gh repo clone` for cloning
- `gh pr create` for PRs

## Workflow
1. Create branch from main
2. Make changes
3. Create PR with template
```

---

## 3. Data Flow During Agent Loop

### 3.1 Message Processing Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Agent Message Processing                           │
└─────────────────────────────────────────────────────────────────────────────┘

1. MESSAGE RECEIVED
   │
   ▼
2. LOAD MEMORY CONTEXT
   │
   ├── Load from MemoryIndex (fast lookup by keywords)
   ├── Retrieve from Long-Term Memory (MEMORY.md)
   ├── Load Today's Notes (daily/{YYYY-MM-DD}.md)
   └── Load Relevant Skill Memories (if skill detected)
   │
   ▼
3. BUILD CONTEXT
   │
   ├── Combine all memory sources
   ├── Apply importance scoring
   ├── Limit context size (~8k tokens default)
   └── Inject into system prompt
   │
   ▼
4. PROCESS WITH LLM
   │
   ├── LLM receives context + message
   ├── LLM may call tools
   ├── Tool execution updates session
   │
   ▼
5. POST-PROCESSING (After LLM Response)
   │
   ├── Analyze response for memory-worthy content
   ├── If importance >= threshold:
   │   ├── Write to appropriate memory layer
   │   └── Update MemoryIndex
   └── Archive if needed (deduplication)
   │
   ▼
6. SAVE SESSION
   │
   └── Save conversation to session.jsonl
```

### 3.2 Memory Retrieval Flow

```python
# Pseudocode: Memory retrieval during context building

async def get_memory_context(
    self,
    query: str,
    max_tokens: int = 8000,
    min_importance: float = 0.3
) -> str:
    """
    Get relevant memories for the current query.
    
    Args:
        query: The user's message to match against
        max_tokens: Maximum tokens for memory context
        min_importance: Minimum importance score to include
    
    Returns:
        Formatted memory context string
    """
    memories = []
    
    # Step 1: Keyword-based retrieval from index
    keywords = extract_keywords(query)
    indexed_memories = self.index.lookup(keywords)
    
    # Step 2: Add from long-term memory
    for memory in indexed_memories:
        if memory.importance >= min_importance:
            memories.append(memory)
    
    # Step 3: Add today's notes (always include recent)
    today_notes = self.read_today()
    if today_notes:
        memories.append(Memory(
            content=today_notes,
            importance=0.7,
            layer="short-term",
            source="daily"
        ))
    
    # Step 4: Add skill memories (if skill detected)
    skill_memories = self._get_skill_memories(query)
    memories.extend(skill_memories)
    
    # Step 5: Sort by importance and limit
    memories.sort(key=lambda m: m.importance, reverse=True)
    memories = limit_by_tokens(memories, max_tokens)
    
    # Step 6: Format for LLM
    return self._format_for_llm(memories)
```

### 3.3 Memory Writing Flow

```python
# Pseudocode: Automatic memory writing after response

async def post_process_memory(
    self,
    session: Session,
    response: str,
    user_message: str
) -> None:
    """
    Analyze response and write important memories.
    
    Args:
        session: Current conversation session
        response: LLM's response
        user_message: Original user message
    """
    # Step 1: Extract potential memories from conversation
    candidate_memories = self.analyzer.extract_memories(
        user_message=user_message,
        assistant_response=response,
        conversation_history=session.messages
    )
    
    # Step 2: Score each candidate
    for memory in candidate_memories:
        memory.importance = self.scorer.score(memory)
        memory.tags = self.tagger.tag(memory)
    
    # Step 3: Write to appropriate layer
    for memory in candidate_memories:
        if memory.importance >= 0.7:
            # High importance: Write to long-term
            self.write_long_term(memory)
            self.index.add(memory)
        elif memory.importance >= 0.4:
            # Medium importance: Write to daily notes
            self.append_to_daily(memory)
        else:
            # Low importance: Working memory only
            self.working_memory.add(memory)
    
    # Step 4: Check for conflicts
    self._resolve_conflicts(candidate_memories)
```

---

## 4. Storage Design

### 4.1 Folder Structure

```
workspace/
├── memory/                          # Main memory directory
│   ├── MEMORY.md                    # Long-term consolidated memory
│   ├── index.json                   # Memory index for fast lookup
│   ├── daily/                       # Daily conversation notes
│   │   ├── 2026-02-07.md
│   │   ├── 2026-02-06.md
│   │   └── ...
│   ├── skills/                      # Skill-specific memories
│   │   └── {skill-name}/
│   │       ├── memory.md
│   │       └── index.json
│   └── archives/                    # Archived/deduplicated memories
│       └── YYYY-MM/
│           └── archived_memories.jsonl
└── skills/
    └── {skill-name}/                # Existing skill structure
        ├── SKILL.md
        └── memory/                  # NEW: Skill memory directory
            ├── context.md
            ├── history.jsonl
            └── index.json
```

### 4.2 File Formats

#### 4.2.1 Long-Term Memory (MEMORY.md)

```markdown
# Long-term Memory

This file stores important information that persists across sessions.
DO NOT DELETE THE HEADER. Add new memories below existing sections.

---

## User Information

[mem_001] User: Alex, prefers Python development, works on AI projects.
[mem_003] User is in timezone UTC+1 (Europe/Paris).

---

## Preferences

[mem_002] User prefers concise responses. Avoid lengthy explanations.
[mem_005] User likes dark mode in terminals.

---

## Project Context

[mem_007] Currently working on nanobot memory system implementation.
[mem_009] Main repository: e:/OpenCode-DEV/nanobot 2/nanobot

---

## Skills & Tools

[mem_004] Frequently uses web search and file editing tools.
[mem_006] Has GitHub skill installed for repository operations.

---

## Important Facts

[mem_008] Memory index file should be updated when writing new memories.

---

*Last updated: 2026-02-07T21:30:00*
*Memory format: [mem_ID] content*
```

#### 4.2.2 Memory Index (index.json)

```json
{
  "version": "1.0",
  "last_updated": "2026-02-07T21:30:00Z",
  "stats": {
    "total_memories": 15,
    "avg_importance": 0.65
  },
  "memories": [
    {
      "id": "mem_001",
      "content": "User: Alex, prefers Python development, works on AI projects.",
      "content_preview": "Alex prefers Python development",
      "tags": ["user", "language", "domain"],
      "importance": 0.9,
      "created_at": "2026-01-10T08:00:00Z",
      "updated_at": "2026-01-10T08:00:00Z",
      "section": "User Information",
      "source": "conversation",
      "line_range": [5, 5]
    }
  ],
  "keywords": {
    "python": ["mem_001", "mem_012"],
    "alex": ["mem_001", "mem_003"],
    "timezone": ["mem_003"],
    "prefers": ["mem_002", "mem_005"]
  }
}
```

#### 4.2.3 Daily Notes (daily/YYYY-MM-DD.md)

```markdown
---
date: 2026-02-07
session_key: cli:user123
topics: [memory, implementation, python]
last_updated: 2026-02-07T21:45:00Z
---

# 2026-02-07

## Conversation Log

### User Query
What's the plan for implementing the memory system?

### Response Summary
Discussed memory architecture with 3 layers: working, short-term, long-term.
Plan includes keyword-based retrieval and importance scoring.

## Key Points
- Memory will use Markdown for human readability
- Index file for fast lookup
- Skill-specific memory in each skill's directory

## Action Items
- [x] Review existing memory.py
- [ ] Design storage format
- [ ] Implement retrieval system

## Code References
- `nanobot/agent/memory.py` - Main memory module
- `nanobot/agent/loop.py` - Agent loop integration
```

#### 4.2.4 Archived Memories (archives/YYYY-MM/archived.jsonl)

```jsonl
{"id": "mem_old_001", "content": "Old memory content", "archived_at": "2026-01-01T00:00:00Z", "reason": "deduplicated"}
{"id": "mem_old_002", "content": "Another old memory", "archived_at": "2026-01-01T00:00:00Z", "reason": "outdated"}
```

### 4.3 Naming Conventions

| Item | Convention | Example |
|------|------------|---------|
| Memory ID | `mem_XXX` (zero-padded 3-digit) | `mem_001`, `mem_042` |
| Daily files | `YYYY-MM-DD.md` | `2026-02-07.md` |
| Archive folders | `YYYY-MM` | `2026-02/` |
| Session keys | `{channel}_{chat_id}` | `cli_user123`, `telegram_456` |
| Skill memories | `{skill}/memory.md` | `github/memory.md` |

---

## 5. Memory Retrieval System

### 5.1 Retrieval Strategies

#### 5.1.1 Keyword-Based Retrieval

```python
class KeywordRetriever:
    """Retrieve memories by keyword matching."""
    
    def __init__(self, index: MemoryIndex):
        self.index = index
    
    def retrieve(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.2
    ) -> list[RetrievalResult]:
        """Retrieve memories matching query keywords."""
        keywords = self._extract_keywords(query)
        results = []
        
        for keyword in keywords:
            if keyword in self.index.keywords:
                for memory_id in self.index.keywords[keyword]:
                    memory = self.index.get_memory(memory_id)
                    score = self._calculate_keyword_score(keyword, query, memory)
                    
                    if score >= min_score:
                        results.append(RetrievalResult(
                            memory=memory,
                            score=score,
                            matched_keywords=[keyword]
                        ))
        
        # Deduplicate and sort by score
        return self._deduplicate_and_sort(results)[:limit]
    
    def _extract_keywords(self, query: str) -> list[str]:
        """Extract keywords from query."""
        # Simple approach: lowercase, remove stopwords
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "do", "does"}
        words = query.lower().split()
        return [w for w in words if w not in stopwords and len(w) > 2]
```

#### 5.1.2 Tag-Based Retrieval

```python
class TagRetriever:
    """Retrieve memories by tags."""
    
    def retrieve(
        self,
        tags: list[str],
        min_importance: float = 0.0,
        limit: int = 20
    ) -> list[Memory]:
        """Get all memories with any of the specified tags."""
        memories = []
        
        for tag in tags:
            if tag in self.index.tags:
                for memory_id in self.index.tags[tag]:
                    memory = self.index.get_memory(memory_id)
                    if memory.importance >= min_importance:
                        memories.append(memory)
        
        return memories[:limit]
```

#### 5.1.3 Time-Based Retrieval

```python
class TimeRetriever:
    """Retrieve memories by time constraints."""
    
    def get_recent(
        self,
        days: int = 7,
        min_importance: float = 0.5
    ) -> list[Memory]:
        """Get memories from the last N days."""
        cutoff = datetime.now() - timedelta(days=days)
        memories = []
        
        for memory in self.index.all_memories:
            if memory.updated_at >= cutoff:
                if memory.importance >= min_importance:
                    memories.append(memory)
        
        return sorted(memories, key=lambda m: m.updated_at, reverse=True)
```

### 5.2 Context Injection Strategy

```python
class MemoryInjector:
    """Inject memories into LLM context."""
    
    def __init__(self, memory_manager: "MemoryManager"):
        self.memory_manager = memory_manager
    
    def build_context(
        self,
        query: str,
        system_prompt: str,
        max_tokens: int = 8000
    ) -> str:
        """
        Build memory context section for system prompt.
        
        Strategy:
        1. Retrieve relevant memories (keyword + tag based)
        2. Add today's notes if relevant
        3. Add skill memories if skill detected
        4. Sort by importance
        5. Truncate to fit token budget
        """
        # Step 1: Retrieve from index
        memories = self.memory_manager.retrieve(
            query=query,
            limit=20,
            min_importance=0.3
        )
        
        # Step 2: Add today's notes (always include summary)
        today_notes = self.memory_manager.read_today()
        if today_notes:
            notes_summary = self._summarize_today(today_notes)
            memories.append(Memory(
                content=notes_summary,
                importance=0.8,
                layer="short-term",
                source="daily_notes"
            ))
        
        # Step 3: Detect and add skill memories
        skill_names = self._detect_skills(query)
        for skill in skill_names:
            skill_memories = self.memory_manager.get_skill_memories(skill)
            memories.extend(skill_memories)
        
        # Step 4: Sort by importance
        memories.sort(key=lambda m: m.importance, reverse=True)
        
        # Step 5: Format and truncate
        context = self._format_memories(memories)
        context = self._truncate_to_tokens(context, max_tokens)
        
        return context
    
    def _format_memories(self, memories: list[Memory]) -> str:
        """Format memories for LLM context."""
        if not memories:
            return ""
        
        parts = ["# Relevant Memories\n"]
        
        for i, memory in enumerate(memories, 1):
            importance_bar = "█" * int(memory.importance * 5)
            parts.append(f"### Memory {i} {importance_bar}")
            parts.append(f"**Source**: {memory.source} | **Tags**: {', '.join(memory.tags)}")
            parts.append("")
            parts.append(memory.content)
            parts.append("")
            parts.append("---")
            parts.append("")
        
        return "\n".join(parts)
```

---

## 6. Memory Writing Logic

### 6.1 Memory Importance Scoring

```python
class ImportanceScorer:
    """Score memories based on importance."""
    
    # Keywords that indicate importance
    IMPORTANT_KEYWORDS = {
        "always", "never", "must", "shouldn't", "prefer", "hate",
        "favorite", "worst", "best", "allergic", "cannot", "can't"
    }
    
    # Patterns that suggest memory-worthy content
    PATTERNS = [
        (r"remember (that|to)", 0.7),
        (r"don't forget", 0.8),
        (r"important", 0.6),
        (r"note that", 0.5),
        (r"user (is|has|works)", 0.7),
        (r"prefers?", 0.6),
        (r"\.{2,}", 0.3),  # Ellipsis might indicate continuation
    ]
    
    def score(self, content: str, context: dict) -> float:
        """
        Calculate importance score (0.0 to 1.0).
        
        Args:
            content: The potential memory content
            context: Additional context (user message, response, etc.)
        
        Returns:
            Importance score between 0 and 1
        """
        score = 0.3  # Base score
        
        # Check for importance keywords
        if any(kw in content.lower() for kw in self.IMPORTANT_KEYWORDS):
            score += 0.3
        
        # Check patterns
        for pattern, bonus in self.PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                score += bonus
        
        # Context factors
        if context.get("is_user_fact", False):
            score += 0.2
        if context.get("is_repeated", False):
            score += 0.1
        
        # Cap at 1.0
        return min(score, 1.0)
```

### 6.2 Memory Writing Rules

```python
class MemoryWriter:
    """Write memories to appropriate layers."""
    
    def __init__(self, memory_manager: "MemoryManager"):
        self.memory_manager = memory_manager
        self.scorer = ImportanceScorer()
    
    async def write_from_conversation(
        self,
        user_message: str,
        assistant_response: str,
        session: Session
    ) -> list[Memory]:
        """
        Analyze conversation and write important memories.
        
        Returns:
            List of memories that were written
        """
        written_memories = []
        
        # Step 1: Extract candidate memories
        candidates = self._extract_candidates(
            user_message=user_message,
            assistant_response=assistant_response,
            history=session.messages
        )
        
        # Step 2: Score each candidate
        for candidate in candidates:
            candidate.importance = self.scorer.score(
                content=candidate.content,
                context={"is_user_fact": candidate.is_user_fact}
            )
        
        # Step 3: Write to appropriate layers
        for candidate in candidates:
            if candidate.importance >= 0.7:
                # High importance: Long-term memory
                memory = self._write_long_term(candidate)
                written_memories.append(memory)
            elif candidate.importance >= 0.4:
                # Medium importance: Daily notes
                self._append_to_daily(candidate)
            else:
                # Low importance: Working memory only (not persisted)
                self.memory_manager.working_memory.add(candidate)
        
        # Step 4: Update index
        if written_memories:
            self.memory_manager.index.rebuild()
        
        return written_memories
    
    def _write_long_term(self, candidate: MemoryCandidate) -> Memory:
        """Write high-importance memory to long-term storage."""
        # Determine appropriate section
        section = self._determine_section(candidate)
        
        # Generate memory ID
        memory_id = self.memory_manager.generate_id()
        
        # Format for MEMORY.md
        memory_entry = f"[{memory_id}] {candidate.content}"
        
        # Append to MEMORY.md
        self.memory_manager.append_to_memory(memory_entry, section)
        
        # Create Memory object
        return Memory(
            id=memory_id,
            content=candidate.content,
            importance=candidate.importance,
            tags=candidate.tags,
            layer="long-term",
            section=section,
            created_at=datetime.now()
        )
    
    def _determine_section(self, candidate: MemoryCandidate) -> str:
        """Determine which section of MEMORY.md to write to."""
        tag_to_section = {
            "user": "User Information",
            "preference": "Preferences",
            "project": "Project Context",
            "skill": "Skills & Tools",
            "fact": "Important Facts",
        }
        
        for tag in candidate.tags:
            if tag in tag_to_section:
                return tag_to_section[tag]
        
        return "Important Facts"
```

### 6.3 Conflict Resolution

```python
class ConflictResolver:
    """Resolve conflicting memories."""
    
    def check_conflicts(self, new_memory: Memory) -> list[Conflict]:
        """
        Check for conflicts with existing memories.
        
        Returns:
            List of potential conflicts
        """
        conflicts = []
        
        # Check for contradictory content
        existing = self.memory_manager.index.get_memories_by_tags(new_memory.tags)
        
        for existing_memory in existing:
            if self._is_contradictory(new_memory, existing_memory):
                conflicts.append(Conflict(
                    new_memory=new_memory,
                    existing_memory=existing_memory,
                    type="contradiction",
                    severity=self._calculate_severity(new_memory, existing_memory)
                ))
        
        # Check for duplicates
        for existing_memory in existing:
            if self._is_duplicate(new_memory, existing_memory):
                conflicts.append(Conflict(
                    new_memory=new_memory,
                    existing_memory=existing_memory,
                    type="duplicate",
                    severity=0.9
                ))
        
        return conflicts
    
    def resolve(self, conflict: Conflict) -> Resolution:
        """
        Resolve a conflict.
        
        Resolution strategies:
        - Keep both (add clarification)
        - Update existing (newer info supersedes)
        - Archive existing (new info contradicts)
        - Ignore (not important enough)
        """
        if conflict.severity < 0.5:
            return Resolution(action="keep_both", note="Low severity conflict")
        
        if conflict.type == "duplicate":
            # Deduplicate
            return Resolution(
                action="archive_existing",
                note="Duplicate memory archived"
            )
        
        if conflict.type == "contradiction":
            # Keep both with clarification
            return Resolution(
                action="keep_both",
                note=f"Contradicts {conflict.existing_memory.id}"
            )
        
        return Resolution(action="keep_both")
```

### 6.4 Memory Update/Delete Rules

```python
class MemoryUpdator:
    """Update and delete memories."""
    
    def update(
        self,
        memory_id: str,
        new_content: str,
        importance: float | None = None
    ) -> bool:
        """Update an existing memory."""
        memory = self.memory_manager.index.get_memory(memory_id)
        if not memory:
            return False
        
        # Update content
        old_content = memory.content
        memory.content = new_content
        
        # Update importance if provided
        if importance is not None:
            memory.importance = importance
        
        # Mark as updated
        memory.updated_at = datetime.now()
        
        # Reindex
        self.memory_manager.index.update(memory)
        
        # Log update
        logger.info(f"Updated memory {memory_id}: '{old_content[:50]}...' -> '{new_content[:50]}...'")
        
        return True
    
    def archive(self, memory_id: str, reason: str = "manual") -> bool:
        """Archive (soft delete) a memory."""
        memory = self.memory_manager.index.get_memory(memory_id)
        if not memory:
            return False
        
        # Move to archive
        archive_path = self.memory_manager.archive_dir / f"{memory_id}.json"
        
        with open(archive_path, "w") as f:
            json.dump({
                "id": memory.id,
                "content": memory.content,
                "importance": memory.importance,
                "tags": memory.tags,
                "archived_at": datetime.now().isoformat(),
                "reason": reason
            }, f, indent=2)
        
        # Remove from active index
        self.memory_manager.index.remove(memory_id)
        
        logger.info(f"Archived memory {memory_id} with reason: {reason}")
        
        return True
```

---

## 7. APIs and Internal Interfaces

### 7.1 MemoryManager Class

```python
# nanobot/agent/memory.py (expanded)

from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any
import json
import re


@dataclass
class Memory:
    """A single memory entry."""
    id: str
    content: str
    importance: float
    tags: list[str] = field(default_factory=list)
    layer: str = "long-term"  # working, short-term, long-term, skill
    source: str = "conversation"
    section: str = "Important Facts"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_index_entry(self) -> dict:
        """Convert to index entry format."""
        return {
            "id": self.id,
            "content": self.content,
            "content_preview": self.content[:100] + "..." if len(self.content) > 100 else self.content,
            "tags": self.tags,
            "importance": self.importance,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "section": self.section,
            "source": self.source
        }


class MemoryManager:
    """
    Main memory management class.
    
    Provides:
    - Memory reading and writing
    - Retrieval by keywords, tags, time
    - Index management
    - Integration with agent loop
    """
    
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.memory_dir = self.workspace / "memory"
        self.daily_dir = self.memory_dir / "daily"
        self.archive_dir = self.memory_dir / "archives"
        
        # Ensure directories exist
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize components
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.index_file = self.memory_dir / "index.json"
        self.index = MemoryIndex(self.index_file)
        
        self.retriever = KeywordRetriever(self.index)
        self.writer = MemoryWriter(self)
        self.updator = MemoryUpdator(self)
        self.working_memory = WorkingMemory()
    
    # ==================== Reading ====================
    
    def read_memory(self) -> str:
        """Read long-term memory file."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""
    
    def read_today(self) -> str:
        """Read today's daily notes."""
        today_file = self.daily_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""
    
    def read_recent_memories(self, days: int = 7) -> list[Memory]:
        """Read memories from the last N days."""
        cutoff = datetime.now() - timedelta(days=days)
        memories = []
        
        for memory in self.index.all_memories:
            if memory.updated_at >= cutoff:
                if memory.importance >= 0.5:
                    memories.append(memory)
        
        return sorted(memories, key=lambda m: m.updated_at, reverse=True)
    
    # ==================== Writing ====================
    
    def write_memory(self, content: str, section: str = "Important Facts") -> Memory:
        """Write a new memory to long-term storage."""
        memory_id = self._generate_id()
        
        memory = Memory(
            id=memory_id,
            content=content,
            importance=0.7,  # Default high importance
            layer="long-term",
            section=section
        )
        
        # Write to MEMORY.md
        entry = f"[{memory_id}] {content}"
        self._append_to_memory_file(entry, section)
        
        # Add to index
        self.index.add(memory)
        
        return memory
    
    def append_to_today(self, content: str) -> None:
        """Append content to today's daily notes."""
        today_file = self.daily_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"
        
        if today_file.exists():
            existing = today_file.read_text(encoding="utf-8")
            content = existing + "\n\n" + content
        else:
            header = f"# {datetime.now().strftime('%Y-%m-%d')}\n\n"
            content = header + content
        
        today_file.write_text(content, encoding="utf-8")
    
    # ==================== Retrieval ====================
    
    def retrieve(
        self,
        query: str,
        limit: int = 10,
        min_importance: float = 0.3
    ) -> list[Memory]:
        """Retrieve relevant memories for a query."""
        return self.retriever.retrieve(query, limit, min_importance)
    
    def retrieve_by_tags(
        self,
        tags: list[str],
        min_importance: float = 0.0,
        limit: int = 20
    ) -> list[Memory]:
        """Retrieve memories by tags."""
        return self.index.get_memories_by_tags(tags, min_importance, limit)
    
    def get_skill_memories(self, skill_name: str) -> list[Memory]:
        """Get memories for a specific skill."""
        skill_memory_dir = self.workspace / "skills" / skill_name / "memory"
        memory_file = skill_memory_dir / "context.md"
        
        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            return [Memory(
                id=f"skill_{skill_name}",
                content=content,
                importance=0.8,
                layer="skill",
                source=skill_name
            )]
        
        return []
    
    # ==================== Context Building ====================
    
    def get_memory_context(
        self,
        query: str,
        max_tokens: int = 8000
    ) -> str:
        """
        Get formatted memory context for LLM.
        
        Combines:
        - Retrieved relevant memories
        - Today's notes summary
        - Skill memories if relevant
        """
        # Retrieve memories
        memories = self.retrieve(query, limit=20, min_importance=0.3)
        
        # Add today's notes
        today = self.read_today()
        if today:
            summary = self._summarize_today(today)
            memories.append(Memory(
                id="today_notes",
                content=summary,
                importance=0.8,
                layer="short-term",
                source="daily"
            ))
        
        # Add skill memories
        skill_names = self._detect_skills(query)
        for skill in skill_names:
            skill_memories = self.get_skill_memories(skill)
            memories.extend(skill_memories)
        
        # Sort by importance
        memories.sort(key=lambda m: m.importance, reverse=True)
        
        # Format
        return self._format_memories(memories, max_tokens)
    
    # ==================== Maintenance ====================
    
    def rebuild_index(self) -> None:
        """Rebuild memory index from MEMORY.md."""
        self.index.rebuild()
    
    def archive_old_memories(self, older_than_days: int = 90) -> int:
        """Archive memories older than specified days."""
        cutoff = datetime.now() - timedelta(days=older_than_days)
        archived = 0
        
        for memory in self.index.all_memories:
            if memory.created_at < cutoff:
                self.updator.archive(memory.id, reason="age")
                archived += 1
        
        return archived
    
    def generate_id(self) -> str:
        """Generate next memory ID."""
        existing_ids = [m.id for m in self.index.all_memories]
        num = 1
        while f"mem_{num:03d}" in existing_ids:
            num += 1
        return f"mem_{num:03d}"
    
    # ==================== Internal Helpers ====================
    
    def _append_to_memory_file(self, entry: str, section: str) -> None:
        """Append entry to MEMORY.md in correct section."""
        content = self.read_memory()
        
        # Simple section append (can be enhanced)
        if section in content:
            # Find section and append before next ##
            # Simplified: append at end
            content += f"\n\n{entry}"
        else:
            content += f"\n\n## {section}\n\n{entry}"
        
        self.memory_file.write_text(content, encoding="utf-8")
    
    def _format_memories(self, memories: list[Memory], max_tokens: int) -> str:
        """Format memories for LLM context."""
        if not memories:
            return ""
        
        parts = ["# Relevant Memories\n"]
        
        for memory in memories:
            parts.append(f"- *[{memory.id}]* {memory.content}")
            parts.append(f"  - importance: {memory.importance:.1f}, tags: {', '.join(memory.tags)}")
        
        result = "\n".join(parts)
        
        # Truncate if needed (rough token estimation)
        if len(result) > max_tokens * 4:  # Rough char-to-token ratio
            result = result[:max_tokens * 4] + "..."
        
        return result
    
    def _summarize_today(self, content: str) -> str:
        """Summarize today's notes for context."""
        # Simple: take first 500 chars if short, else first paragraph
        if len(content) < 500:
            return content
        return content.split("\n\n")[0][:500]
    
    def _detect_skills(self, query: str) -> list[str]:
        """Detect which skills might be relevant to the query."""
        # Simple keyword matching
        skills_path = self.workspace / "skills"
        if not skills_path.exists():
            return []
        
        skills = []
        for skill_dir in skills_path.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                skill_name = skill_dir.name
                # Check if skill name or keywords appear in query
                if skill_name.lower() in query.lower():
                    skills.append(skill_name)
        
        return skills
```

### 7.2 MemoryIndex Class

```python
class MemoryIndex:
    """In-memory index with JSON persistence."""
    
    def __init__(self, index_file: Path):
        self.index_file = index_file
        self.memories: dict[str, Memory] = {}
        self.keywords: dict[str, list[str]] = {}
        self.tags: dict[str, list[str]] = {}
        self.load()
    
    def load(self) -> None:
        """Load index from file."""
        if self.index_file.exists():
            try:
                data = json.loads(self.index_file.read_text(encoding="utf-8"))
                for entry in data.get("memories", []):
                    memory = Memory(
                        id=entry["id"],
                        content=entry["content"],
                        importance=entry["importance"],
                        tags=entry.get("tags", []),
                        layer=entry.get("layer", "long-term"),
                        section=entry.get("section", "Important Facts"),
                        created_at=datetime.fromisoformat(entry["created_at"]),
                        updated_at=datetime.fromisoformat(entry["updated_at"])
                    )
                    self._add_to_indexes(memory)
            except Exception as e:
                logger.error(f"Failed to load memory index: {e}")
    
    def save(self) -> None:
        """Save index to file."""
        data = {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
            "memories": [m.to_index_entry() for m in self.memories.values()]
        }
        self.index_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    
    def add(self, memory: Memory) -> None:
        """Add a memory to the index."""
        self.memories[memory.id] = memory
        self._add_to_indexes(memory)
        self.save()
    
    def remove(self, memory_id: str) -> None:
        """Remove a memory from the index."""
        if memory_id in self.memories:
            memory = self.memories[memory_id]
            self._remove_from_indexes(memory)
            del self.memories[memory_id]
            self.save()
    
    def update(self, memory: Memory) -> None:
        """Update a memory in the index."""
        if memory.id in self.memories:
            self._remove_from_indexes(self.memories[memory.id])
            self._add_to_indexes(memory)
            self.save()
    
    def get_memory(self, memory_id: str) -> Memory | None:
        """Get a memory by ID."""
        return self.memories.get(memory_id)
    
    def get_memories_by_tags(
        self,
        tags: list[str],
        min_importance: float = 0.0,
        limit: int = 20
    ) -> list[Memory]:
        """Get memories that have any of the specified tags."""
        results = []
        for tag in tags:
            if tag in self.tags:
                for memory_id in self.tags[tag]:
                    memory = self.memories.get(memory_id)
                    if memory and memory.importance >= min_importance:
                        results.append(memory)
        return results[:limit]
    
    def rebuild(self) -> None:
        """Rebuild index from MEMORY.md file."""
        self.memories = {}
        self.keywords = {}
        self.tags = {}
        
        # Parse MEMORY.md for memories
        memory_file = self.index_file.parent / "MEMORY.md"
        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            # Extract [mem_XXX] entries
            pattern = r'\[(mem_\d+)\]\s*(.+?)(?=\n\[|\n##|\n*$|\n---)'
            for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
                memory_id, memory_content = match.groups()
                memory_content = memory_content.strip()
                
                # Estimate importance based on content
                importance = self._estimate_importance(memory_content)
                tags = self._extract_tags(memory_content)
                
                memory = Memory(
                    id=memory_id,
                    content=memory_content,
                    importance=importance,
                    tags=tags,
                    layer="long-term"
                )
                self._add_to_indexes(memory)
        
        self.save()
    
    @property
    def all_memories(self) -> list[Memory]:
        """Get all memories."""
        return list(self.memories.values())
    
    # ==================== Internal ====================
    
    def _add_to_indexes(self, memory: Memory) -> None:
        """Add memory to keyword and tag indexes."""
        # Add to tag index
        for tag in memory.tags:
            if tag not in self.tags:
                self.tags[tag] = []
            if memory.id not in self.tags[tag]:
                self.tags[tag].append(memory.id)
        
        # Add keywords to index
        keywords = self._extract_keywords(memory.content)
        for keyword in keywords:
            if keyword not in self.keywords:
                self.keywords[keyword] = []
            if memory.id not in self.keywords[keyword]:
                self.keywords[keyword].append(memory.id)
    
    def _remove_from_indexes(self, memory: Memory) -> None:
        """Remove memory from keyword and tag indexes."""
        for tag in memory.tags:
            if tag in self.tags and memory.id in self.tags[tag]:
                self.tags[tag].remove(memory.id)
                if not self.tags[tag]:
                    del self.tags[tag]
        
        keywords = self._extract_keywords(memory.content)
        for keyword in keywords:
            if keyword in self.keywords and memory.id in self.keywords[keyword]:
                self.keywords[keyword].remove(memory.id)
                if not self.keywords[keyword]:
                    del self.keywords[keyword]
    
    def _extract_keywords(self, content: str) -> list[str]:
        """Extract keywords from content for indexing."""
        # Simple: lowercase words, filter stopwords
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                     "being", "have", "has", "had", "do", "does", "did", "will",
                     "would", "could", "should", "may", "might", "must", "shall",
                     "can", "need", "dare", "ought", "used", "to", "of", "in",
                     "for", "on", "with", "at", "by", "from", "as", "into",
                     "through", "during", "before", "after", "above", "below",
                     "between", "under", "again", "further", "then", "once"}
        
        words = re.findall(r'\b[a-z]+\b', content.lower())
        return [w for w in words if w not in stopwords and len(w) > 2]
    
    def _extract_tags(self, content: str) -> list[str]:
        """Extract tags from content (custom #tag format or infer)."""
        tags = []
        
        # Look for #tag format
        tags.extend(re.findall(r'#(\w+)', content))
        
        # Infer tags based on content
        content_lower = content.lower()
        
        if "user" in content_lower or "name" in content_lower:
            tags.append("user")
        if "prefer" in content_lower or "like" in content_lower:
            tags.append("preference")
        if "project" in content_lower or "working" in content_lower:
            tags.append("project")
        if "skill" in content_lower or "tool" in content_lower:
            tags.append("skill")
        
        return list(set(tags))
    
    def _estimate_importance(self, content: str) -> float:
        """Estimate importance from content (for rebuild)."""
        scorer = ImportanceScorer()
        return scorer.score(content, {})
```

### 7.3 Tool Access Patterns

```python
# Tools that agents can use to interact with memory

from nanobot.agent.tools.base import Tool, ToolResult


class RememberTool(Tool):
    """Tool to explicitly store a memory."""
    
    name = "remember"
    description = "Store important information for later recall"
    
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The information to remember"
            },
            "importance": {
                "type": "number",
                "description": "Importance score (0-1), default 0.7",
                "default": 0.7
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for categorization",
                "default": []
            }
        },
        "required": ["content"]
    }
    
    def __init__(self, memory_manager: MemoryManager):
        self.memory = memory_manager
    
    async def execute(self, content: str, importance: float = 0.7, tags: list[str] = None) -> ToolResult:
        """Execute the remember tool."""
        memory = self.memory.write_memory(
            content=content,
            section="Important Facts"
        )
        return ToolResult(success=True, output=f"Remembered: [{memory.id}] {content[:100]}...")


class RecallTool(Tool):
    """Tool to recall memories."""
    
    name = "recall"
    description = "Recall relevant memories based on a query"
    
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Query to search memories"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter by tags"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum memories to return",
                "default": 5
            }
        },
        "required": ["query"]
    }
    
    def __init__(self, memory_manager: MemoryManager):
        self.memory = memory_manager
    
    async def execute(self, query: str, tags: list[str] = None, limit: int = 5) -> ToolResult:
        """Execute the recall tool."""
        if tags:
            memories = self.memory.retrieve_by_tags(tags, limit=limit)
        else:
            memories = self.memory.retrieve(query, limit=limit)
        
        if not memories:
            return ToolResult(success=True, output="No relevant memories found.")
        
        formatted = "\n".join([
            f"[{m.id}] {m.content} (importance: {m.importance})"
            for m in memories
        ])
        
        return ToolResult(success=True, output=formatted)


class ForgetTool(Tool):
    """Tool to remove a memory."""
    
    name = "forget"
    description = "Remove a specific memory from storage"
    
    parameters = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The memory ID to remove (e.g., mem_001)"
            },
            "reason": {
                "type": "string",
                "description": "Reason for forgetting"
            }
        },
        "required": ["memory_id"]
    }
    
    def __init__(self, memory_manager: MemoryManager):
        self.memory = memory_manager
    
    async def execute(self, memory_id: str, reason: str = "manual") -> ToolResult:
        """Execute the forget tool."""
        success = self.memory.updator.archive(memory_id, reason)
        if success:
            return ToolResult(success=True, output=f"Archived memory {memory_id}")
        return ToolResult(success=False, error=f"Memory {memory_id} not found")
```

---

## 8. Implementation Roadmap

### Phase 1: Minimal Viable Memory

**Goal**: Basic persistent memory without semantic complexity.

**Duration**: 1-2 days

**Deliverables**:
1. Enhanced [`MemoryStore`](nanobot/agent/memory.py) class
2. Memory index file (`index.json`)
3. Basic keyword extraction and lookup
4. Memory writing from agent loop

**Changes**:
- Modify `nanobot/agent/memory.py` to add `MemoryManager` class
- Add `index.json` support
- Add `rebuild_index()` method
- Integrate into `ContextBuilder.build_system_prompt()`

**Code Estimate**: ~400 lines

**Files Modified**:
- `nanobot/agent/memory.py`
- `nanobot/agent/context.py` (memory context integration)

**Files Created**:
- `nanobot/agent/memory.py` (expanded with new classes)

### Phase 2: Structured Long-Term Memory

**Goal**: Organized memory sections and tagging.

**Duration**: 1-2 days

**Deliverables**:
1. Section-based memory organization
2. Tag-based retrieval
3. Memory importance scoring
4. Conflict detection (basic)

**Changes**:
- Add `ImportanceScorer` class
- Add `MemoryIndex` class with tag support
- Enhance `MEMORY.md` format with sections
- Add tag extraction from memory content

**Code Estimate**: ~400 lines

**Files Modified**:
- `nanobot/agent/memory.py`

### Phase 3: Semantic Retrieval

**Goal**: Improved memory retrieval (still keyword-based, enhanced).

**Duration**: 2-3 days

**Deliverables**:
1. Multi-strategy retrieval (keyword + tag + time)
2. Context-aware injection
3. Working memory for current session
4. Skill-specific memory support

**Changes**:
- Add `KeywordRetriever`, `TagRetriever`, `TimeRetriever` classes
- Add `WorkingMemory` class for session context
- Add skill memory directories support
- Enhance `get_memory_context()` in `ContextBuilder`

**Code Estimate**: ~500 lines

**Files Created/Modified**:
- `nanobot/agent/memory.py`
- `nanobot/agent/context.py`

### Phase 4: Advanced Features

**Goal**: Polish and advanced capabilities.

**Duration**: 2-3 days

**Deliverables**:
1. Memory tools (`remember`, `recall`, `forget`)
2. Conflict resolution system
3. Memory archive and cleanup
4. Memory analytics/debugging

**Changes**:
- Add `RememberTool`, `RecallTool`, `ForgetTool`
- Add `ConflictResolver` class
- Add `MemoryUpdator` with archive support
- Add CLI commands for memory management
- Add memory statistics/debugging

**Code Estimate**: ~400 lines

**Files Created/Modified**:
- `nanobot/agent/memory.py`
- `nanobot/agent/tools/` (new memory tools)
- `nanobot/cli/commands.py`

### Phase 5: Testing and Documentation

**Goal**: Verify correctness and document.

**Duration**: 1-2 days

**Deliverables**:
1. Unit tests for memory module
2. Integration tests with agent loop
3. Memory management documentation

**Code Estimate**: ~200 lines (tests)

**Files Created**:
- `tests/test_memory.py`

---

## 9. Code Summary

### Total Line Count

| Phase | New Lines | Modified Lines |
|-------|-----------|----------------|
| Phase 1 | 400 | 50 |
| Phase 2 | 400 | 0 |
| Phase 3 | 500 | 50 |
| Phase 4 | 400 | 50 |
| Phase 5 | 200 (tests) | 0 |
| **Total** | **~1900** | **~150** |

### Key Files

| File | Purpose | Lines |
|------|---------|-------|
| `nanobot/agent/memory.py` | Main memory module | ~1300 |
| `nanobot/agent/context.py` | Context building | +50 |
| `nanobot/agent/loop.py` | Agent loop integration | +50 |
| `nanobot/agent/tools/memory.py` | Memory tools | ~250 |
| `tests/test_memory.py` | Memory tests | ~200 |

---

## 10. Integration with Existing Codebase

### 10.1 ContextBuilder Integration

```python
# In nanobot/agent/context.py

class ContextBuilder:
    # ... existing code ...
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        parts = []
        
        # Core identity
        parts.append(self._get_identity())
        
        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # NEW: Memory context with query awareness
        memory_context = self.memory.get_memory_context(query="")
        if memory_context:
            parts.append(f"# Memory\n\n{memory_context}")
        
        # Skills ...
```

### 10.2 AgentLoop Integration

```python
# In nanobot/agent/loop.py

class AgentLoop:
    # ... existing code ...
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        # ... existing processing ...
        
        # NEW: After session save, analyze for memory-worthy content
        if final_content:
            await self.memory.writer.write_from_conversation(
                user_message=msg.content,
                assistant_response=final_content,
                session=session
            )
        
        return response
```

---

## 11. Constraints Compliance

| Constraint | Compliance |
|------------|------------|
| Under 2k lines | ~1900 lines estimated |
| No heavy dependencies | Only stdlib + existing deps |
| Local-first | All files in workspace |
| Human-readable | Markdown + JSON formats |
| Transparent | Index files for debugging |
| Single-user first | Optimized for local use |
| Easy to extend | Modular class design |

---

## 12. Migration Path

### Existing `MemoryStore` Compatibility

The new `MemoryManager` class extends the existing `MemoryStore` pattern:

```python
# Backward compatibility alias
MemoryStore = MemoryManager
```

All existing methods (`read_today()`, `append_today()`, etc.) are preserved with the same signatures.

### One-Time Migration

```python
# Migration script (run once)

def migrate_existing_memory(workspace: Path):
    """Migrate existing memory format to new index-based format."""
    manager = MemoryManager(workspace)
    
    # Check if migration needed
    if manager.index_file.exists():
        print("Already migrated")
        return
    
    # Rebuild index from existing MEMORY.md
    manager.rebuild_index()
    print(f"Migrated {len(manager.index.all_memories)} memories")
```

---

## 13. Debugging and Observability

### Memory Statistics

```python
# CLI command: nanobot memory stats

def memory_stats(workspace: Path):
    """Display memory statistics."""
    manager = MemoryManager(workspace)
    
    print(f"Total memories: {len(manager.index.all_memories)}")
    print(f"By importance:")
    for mem in sorted(manager.index.all_memories, key=lambda m: m.importance, reverse=True)[:10]:
        print(f"  [{mem.importance:.1f}] {mem.content[:50]}...")
    
    print(f"\nTop tags:")
    for tag, ids in sorted(manager.index.tags.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
        print(f"  {tag}: {len(ids)} memories")
```

### Memory Dump

```python
# CLI command: nanobot memory dump

def dump_memories(workspace: Path, format: str = "markdown"):
    """Dump all memories in readable format."""
    manager = MemoryManager(workspace)
    
    for memory in manager.index.all_memories:
        print(f"[{memory.id}] {memory.content}")
        print(f"   importance: {memory.importance}, tags: {', '.join(memory.tags)}")
```

---

## 14. Future Enhancements (Post-Phase 4)

| Feature | Complexity | Description |
|---------|------------|-------------|
| Semantic embeddings | Medium | Use sentence-transformers for similarity |
| Vector storage | Medium | Add Qdrant/Chroma support |
| Memory summarization | Low | Summarize old memories |
| Cross-session linking | Low | Link related memories |
| Memory analytics | Low | Pattern analysis |
| User memory UI | High | Web interface for memory management |
