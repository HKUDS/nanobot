# Product Intent Brief — nanobot Memory Architecture

> **Authority note:** This document is the highest-authority statement of product intent.

---

## 1. Problem and User

- **Primary user(s):** Eric (power user of AI assistants), and eventually other users who want persistent AI memory
- **Context / current workflow:** 
  - Chat with AI assistants via Telegram, CLI, or other channels
  - Conversations exist in isolated sessions
  - Periodic compaction loses context and "the thread" of what was being discussed
  - Switching topics mid-conversation causes confusion or context loss
  - Starting new sessions means the AI "forgets" everything unless explicitly reminded
- **Pain points (ranked):**
  1. Compaction destroys continuity mid-conversation
  2. Topic switches cause the AI to lose context of what was being discussed
  3. No true persistent memory — each session feels like meeting a stranger
  4. Can't reference past conversations naturally ("remember when we discussed X?")
  5. Context windows fill with irrelevant history instead of what's actually needed
- **Why now (trigger):** Building nanobot as an experimental platform for testing novel memory architectures before potentially integrating into OpenClaw/Kai

---

## 2. Outcome

- **Desired outcome:** An AI assistant with true persistent memory that feels like talking to a person who actually remembers
- **What changes for the user:** 
  - Can switch topics mid-conversation and come back seamlessly
  - Can reference past conversations naturally from any channel
  - No more jarring compaction interruptions
  - Sessions become irrelevant — it's always the same "person"
  - Context stays tight and relevant, not bloated with full history
- **Success looks like:** 
  - User asks "What's the status of clawOS?" and gets accurate answer based on past discussions
  - User goes off on a tangent, then says "anyway, back to what we were working on" and the AI correctly restores context
  - User can chat from Telegram in the morning and Signal in the evening with full continuity
- **Primary success signal:** User can have a multi-day, multi-topic conversation that feels continuous and coherent, without explicit reminders or context management

> **Failure boundary:** If the system cannot recall relevant past conversations when asked, or regularly provides wrong/outdated context, the product is a failure.

---

## 3. In-Scope Capabilities (v1)

<!-- List as user-facing behaviors, not features -->

- [ ] Every conversational turn is persisted and searchable
- [ ] User can ask about past conversations and get accurate responses
- [ ] Topic switches are handled gracefully — old context filed away, retrievable later
- [ ] Simple queries get fast responses (no unnecessary memory lookup latency)
- [ ] Complex queries that need memory get a "one sec" acknowledgment before full response
- [ ] Entity knowledge accumulates over time in dossiers (people, projects, concepts)
- [ ] The assistant can say "I don't have that context" and ask the memory system for more
- [ ] Conversations from any channel contribute to the same memory
- [ ] Triage sensitivity is configurable (slider 1-10 for memory lookup likelihood)
- [ ] Memory lookups show streaming "thinking" updates to user
- [ ] Memory follow-ups visible as normal tool calls

---

## 4. Explicit Non-Goals (v1)

<!-- What we will NOT do, even if it seems valuable -->

- Multi-user memory (this is personal assistant memory, not shared knowledge base)
- External document ingestion (focus is on conversation memory, not RAG over files)
- Perfect entity extraction (acceptable to miss some, catch up over time)
- Sub-second latency for all queries (acceptable to have "thinking" delay for complex lookups)
- Handling adversarial inputs or prompt injection in memory
- Mobile/native apps (CLI and existing chat channels only)

---

## 5. Primary User Journeys

### Journey A: Simple Query (Fast Path)
1. User sends "What's 2+2?"
2. Triage agent determines no memory needed
3. Main agent responds immediately: "4"
4. Turn is logged to conversation store for future reference

### Journey B: Memory-Required Query
1. User sends "What did we decide about the clawOS architecture?"
2. Triage agent determines memory lookup needed
3. User receives quick acknowledgment: "Let me check on that..."
4. Memory agent searches conversation store, pulls relevant turns
5. Memory agent retrieves clawOS dossier
6. Memory agent synthesizes context packet
7. Main agent receives context + query, generates informed response
8. Turn and response logged to conversation store

### Journey C: Topic Switch and Return
1. User is discussing Project A
2. User says "Oh, quick question about Project B"
3. Triage routes to memory agent, which builds Project B context
4. Conversation continues about Project B
5. User says "Okay, back to Project A"
6. Memory agent retrieves Project A context from earlier in conversation + dossier
7. Conversation resumes seamlessly

### Journey D: Follow-up Request
1. User asks about something
2. Triage passes directly to main agent (seemed simple)
3. Main agent realizes it lacks context
4. Main agent calls memory lookup tool: "Tell me about X"
5. Memory agent returns context packet
6. Main agent completes response

---

## 6. Quality Bar

- **Must-not-fail behaviors:**
  - Never lose a conversation turn (durability is critical)
  - Never confidently state wrong information from memory (accuracy > coverage)
  - Always acknowledge when doing a memory lookup (no silent long pauses)
  - Main agent must be able to request more context if memory agent missed something
- **Acceptable trade-offs (v1):**
  - Occasional false positives on triage (memory lookup when not needed) — costs latency, not correctness
  - Entity extraction misses some entities — can improve over time
  - Dossiers may have stale information until next relevant conversation updates them
  - First implementation may have higher latency than ideal
- **Performance expectations:**
  - Simple queries (no memory): < 2 seconds
  - Memory queries: < 5 seconds with acknowledgment after < 1 second
  - Ingestion can be slightly delayed (eventual consistency acceptable)
- **Correctness expectations:**
  - Retrieved context should be relevant > 80% of the time
  - When context is retrieved, it should be accurate (not hallucinated or confused with other entities)
  - Dossiers should reflect most recent known state of entities

---

## 7. Constraints

- **Privacy / data constraints:**
  - All data stored locally (no cloud storage of conversations)
  - User owns their memory data
  - Ability to delete specific memories or entire history
- **Budget posture:**
  - Triage and memory agents should use cheap/small models (Haiku-class, ~$0.25-1.25/M tokens)
  - Main agent can use expensive models (Opus/Sonnet, $15-75/M tokens)
  - Goal is to reduce main model token usage by providing tight, relevant context
  - Local models preferred where quality is sufficient
- **Timeline posture:**
  - Experimental/learning-oriented — quality of learning > speed of delivery
  - Build in layers, each independently testable
  - v1 can be rough around edges if core concept is validated

### Assumptions

- nanobot's existing multi-provider architecture can route to different models
- Hybrid search (vector + BM25) is necessary for good retrieval
- Small models (Haiku, qwen-small) can handle entity extraction and context synthesis
- Users will primarily interact via text (voice/image are out of scope for v1)
- Single-user deployment (no concurrent users hitting same memory store)

---

## 8. Acceptance Tests

<!-- Given / When / Then format. 5-12 tests. -->

1. **Given** a previous conversation about "clawOS project" **When** user asks "What's the status of clawOS?" **Then** the response accurately reflects the most recent discussion of clawOS

2. **Given** no relevant memory exists **When** user asks about something never discussed **Then** assistant says it doesn't have that information rather than hallucinating

3. **Given** user is mid-conversation about Topic A **When** user switches to Topic B then returns to Topic A **Then** context for Topic A is correctly restored

4. **Given** a simple arithmetic question **When** user asks "What's 15 * 7?" **Then** response arrives in < 2 seconds without memory lookup

5. **Given** a question requiring memory **When** user asks about past discussions **Then** user receives acknowledgment within 1 second that lookup is happening

6. **Given** triage incorrectly skips memory lookup **When** main agent doesn't have needed context **Then** main agent requests context from memory agent and completes response correctly

7. **Given** entity "Rebecca" mentioned in past conversations **When** user asks "What does Rebecca do?" **Then** response includes information from Rebecca dossier (e.g., "school teacher")

8. **Given** contradictory information over time (said X in January, Y in March) **When** user asks about that topic **Then** response reflects the more recent information (Y)

9. **Given** conversations across multiple channels (Telegram, CLI) **When** user references past discussion from different channel **Then** memory correctly retrieves it regardless of original channel

10. **Given** the system has been running for days **When** checking data integrity **Then** no conversation turns have been lost

---

## 9. Deferred Implementation Questions

<!-- "How" questions to resolve later -->

- What embedding model to use? (OpenAI, local, Voyage?)
- What vector database backend? (SQLite+sqlite-vec, LanceDB, ChromaDB?)
- What's the dossier schema? (Fields, versioning, update triggers?)
- How granular should dossiers be? (One per person? Per project? Per concept?)
- How does ingestion trigger? (Synchronous? Batch? Event-driven?)
- What's the memory agent's ReAct loop structure?
- How do we handle memory agent timeouts?
- Should there be memory "decay" for very old conversations?

---

## 10. Open Questions

<!-- True intent blockers only. Aim for ≤3. -->

None — all resolved.

### Resolved Questions

1. **Triage balance:** Err toward memory lookup initially. Make it configurable via a slider (1-10) indicating likelihood of requesting memory lookup.

2. **"Give me a sec" UX:** Both immediate message AND typing indicator. Memory agent can provide streaming "thinking" updates to give user feedback during lookup.

3. **Follow-up visibility:** Handled like any other tool call — visible to user as part of normal tool-use flow.

---

## 11. Intent Clarity Self-Check

- [x] No section relies on inferred preferences (discussed explicitly with Eric)
- [x] Every capability maps to ≥1 acceptance test
- [x] No non-goal is contradicted elsewhere
- [x] All assumptions are explicit
- [x] Open questions resolved
