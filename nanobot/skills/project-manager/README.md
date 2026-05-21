# 📂 Project Manager Skill

**Project Context Isolation & State Management System for AI Agents**

## Problem

AI agents are stateless — each conversation is a fresh start. But projects have continuity: progress, decisions, and context that span multiple sessions. Without a state management system:

1. **Memory explosion**: All project progress crammed into `MEMORY.md` → 1000+ lines, slow retrieval
2. **Context pollution**: Project A's progress leaks into Project B's files
3. **Lost breakpoints**: User says "continue last project" → agent has no idea which one or where it left off
4. **Over-engineering**: Tiny tasks ("rename a variable") forced into full project templates

## Solution

A per-project `STATUS.md` system — the agent's "external hard drive":

```
workspace/projects/
├── index.md              # Auto-maintained project registry
├── {project-name}/
│   ├── STATUS.md         # Progress, todos, key decisions
│   ├── docs/             # Proposals, reports
│   └── src/              # Code, deliverables
└── _archive/             # Completed/abandoned projects
```

## Key Features

| Feature | Description |
|---------|-------------|
| **Physical Isolation** | Each project has its own `STATUS.md` — no shared state |
| **Intent Recognition** | No rigid keywords — infers "new/resume/pause/switch" from context |
| **Tiered Templates** | Full (A) for multi-phase projects, Lightweight (B) for single tasks |
| **Concurrent-Safe** | Read-merge-write pattern prevents multi-session overwrites |
| **Index Self-Healing** | Auto-creates `index.md`, auto-adds missing projects |
| **Memory Boundary** | Project progress in `STATUS.md`, user preferences in `MEMORY.md` — never mixed |

## Workflow

1. **New Project** → Create directory + STATUS.md + update index
2. **Resume** → Fuzzy match → Force read STATUS.md → Sync summary
3. **Save State** → Persist conclusions → Update index status
4. **Switch** → Save current → Resume target
5. **Archive** → Move to `_archive/` → Preserve history

## Quantified Impact

| Metric | Before | After |
|--------|--------|-------|
| MEMORY.md size | 1153 lines | 167 lines (85% reduction) |
| Project recovery time | User must re-describe context | Read STATUS.md, <1 second |
| Context pollution risk | High (all projects mixed) | Low (physical isolation) |
| Small task overhead | Full 5-module template | Lightweight 2-3 modules |

## Installation

Place `SKILL.md` in `~/.nanobot/workspace/skills/project-manager/` and start a new session.

---

*Designed and battle-tested across multiple AI agent instances (Feishu, WeChat, CLI) with concurrent session support.*
