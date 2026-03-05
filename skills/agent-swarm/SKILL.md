# Agent Swarm Skill

## Purpose
Simulate a team of specialized AI agents collaborating on complex tasks within a single LLM call. Inspired by TinyClaw's team management and NanoClaw's Agent Swarm pattern, implemented as software-layer enhancement without architectural changes.

## Trigger

**Explicit trigger**: User types `/swarm {task description}`
**Auto-trigger**: Complex tasks that match:
- Multi-domain expertise required (technical + business + risk)
- Architecture/design decisions
- Tasks with >3 distinct phases
- Tasks where user asks for "comprehensive analysis" or "review from multiple angles"

## Available Agent Roles

| Role | Icon | Expertise | When to Use |
|------|------|-----------|-------------|
| Researcher | 🔍 | Information gathering, web search, data collection | Need facts, competitors, market data |
| Architect | 🏗️ | System design, technical decisions, structure | Building something, choosing tech |
| Critic | ⚠️ | Risk identification, edge cases, failure modes | High-stakes decisions, production systems |
| Writer | ✍️ | Synthesis, documentation, clear communication | Final output needs polish |
| Strategist | 🎯 | Business strategy, positioning, opportunities | Business decisions, market entry |
| Analyst | 📊 | Data analysis, metrics, quantitative evaluation | Performance, ROI, comparison |

## Execution Protocol

### Phase 1: Task Analysis
Coordinator (you) analyzes the task and selects 2-4 relevant agents.

### Phase 2: Parallel Processing
Each selected agent contributes their perspective in sequence:
1. Researcher gathers facts (if needed)
2. Architect proposes solutions (if technical)
3. Strategist evaluates business impact (if applicable)
4. Critic identifies risks and edge cases
5. Analyst provides metrics/comparison (if data-driven)

### Phase 3: Conflict Resolution
Coordinator identifies conflicts between agent outputs and resolves them.

### Phase 4: Synthesis
Writer (or Coordinator) produces final integrated output.

## Output Format

```markdown
## 🎯 Task Overview
[Coordinator summary of what needs to be done]

## 🔍 Research Findings
[What Researcher found - facts, data, context]

## 🏗️ Technical Approach  
[Architect's design and reasoning]

## 🎯 Strategic Assessment
[Strategist's business analysis]

## ⚠️ Risk Analysis
[Critic's concerns and mitigations]

## 📊 Comparative Analysis
[Analyst's metrics if applicable]

## ✅ Final Recommendation
[Coordinator's integrated conclusion with clear action items]
```

## Rules

1. **Never expose the simulation** - Don't say "the Researcher agent thinks...", just present findings
2. **Be selective** - Not every task needs all agents; choose 2-4 most relevant
3. **Conflict resolution is key** - When agents disagree, explain the trade-off and make a decision
4. **End with actionable output** - Every swarm response must have clear next steps
5. **Respect token limits** - Be concise; full swarm output should fit in context window

## Checkpoint System

For long-running swarm tasks:
- Save progress to `.nanobot/workspace/checkpoints/swarm-{timestamp}.md`
- Include: completed phases, key decisions, pending items
- Support `/resume swarm-{id}` to continue

## Examples

### Example 1: Architecture Decision
```
User: "/swarm Should I use PostgreSQL or MongoDB for my AI assistant's memory system?"

Response:
## 🎯 Task Overview
Choose database for AI assistant memory system with vector search requirements.

## 🔍 Research Findings
- PostgreSQL + pgvector: Mature, ACID, supports hybrid search
- MongoDB Atlas Vector Search: Native vector support, flexible schema
- Both support the ~100k document scale needed

## 🏗️ Technical Approach
PostgreSQL + pgvector recommended:
- ACID compliance critical for memory consistency
- pgvector performs well at this scale (benchmarks show <50ms query time)
- Easier backup/restore for user data

## ⚠️ Risk Analysis
- Schema migrations: PostgreSQL requires more planning than MongoDB
- Vector search performance: May degrade at >1M vectors (future scaling concern)
- Team expertise: If team knows MongoDB better, learning curve is real

## ✅ Final Recommendation
**Use PostgreSQL + pgvector** for MVP. Reasons:
1. Data consistency > schema flexibility for memory system
2. Mature ecosystem reduces operational risk
3. Migration path exists if we hit scaling limits later

**Next Steps:**
1. Set up PostgreSQL with pgvector extension
2. Design schema with JSONB for flexible metadata
3. Benchmark with expected data volume
4. Document backup/recovery procedures
```

### Example 2: Business Strategy
```
User: "/swarm I'm building an AI coding assistant. Should I target indie developers or enterprise teams?"

Response:
## 🎯 Task Overview
Choose target market for AI coding assistant MVP.

## 🔍 Research Findings
- Indie dev tools: Lower ACV ($20-50/month), faster sales cycle, high churn
- Enterprise dev tools: High ACV ($500-2000/month), long sales cycle, sticky
- Competition: GitHub Copilot dominates enterprise, indie market fragmented
- Trend: "AI for developers" is hot, window is 12-18 months

## 🎯 Strategic Assessment
Indie-first strategy:
- Pros: Faster feedback, easier distribution (Twitter, Product Hunt)
- Cons: Hard to monetize, support burden high

Enterprise-first strategy:
- Pros: Real revenue faster, defensible moat with integrations
- Cons: 6-12 month sales cycles, need compliance/security features

## 📊 Comparative Analysis
| Metric | Indie | Enterprise |
|--------|-------|------------|
| Time to $1k MRR | 1-2 months | 6-12 months |
| Time to $10k MRR | 12-18 months | 12-18 months |
| Support hours/$ | High | Low |
| Churn rate | 15-20%/month | 2-5%/month |

## ⚠️ Risk Analysis
- Indie: "Tool fatigue", competition from free alternatives
- Enterprise: Need SOC2, SSO, which takes 3-6 months to build

## ✅ Final Recommendation
**Start indie, pivot to enterprise** within 6 months:
1. **Months 1-3**: Build for indie, get 100 active users, iterate on product
2. **Months 4-6**: Add enterprise features (SSO, audit logs) while maintaining indie tier
3. **Month 6+**: Enterprise sales with proven product

This captures indie speed with enterprise upside.
```

## Integration with Memory System

After swarm completes:
1. Extract key decisions to MEMORY.md Timeline
2. Link to checkpoint file if task was long-running
3. Tag with `[Swarm]` for future reference

Example memory entry:
```
- **2026-03-04 11:30** [Swarm] Database decision: PostgreSQL+pgvector over MongoDB → [checkpoint](/path/to/checkpoint)
```
