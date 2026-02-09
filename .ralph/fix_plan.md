# fix_plan.md — nanobot Memory Architecture

## Phase 1: Foundation — Conversation Store

- [ ] Create `nanobot/memory/__init__.py` with module exports
- [ ] Create `nanobot/memory/embedder.py` with Embedder protocol and SentenceTransformerEmbedder
- [ ] Create `nanobot/memory/store.py` with Turn dataclass and ConversationStore class
- [ ] Implement ConversationStore.add_turn() with embedding and prev/next linking
- [ ] Implement ConversationStore.get_turn() and get_thread()
- [ ] Create `tests/test_store.py` with add, get, and thread traversal tests
- [ ] Create `nanobot/memory/search.py` with HybridSearch class
- [ ] Implement HybridSearch.search() with vector + BM25 fusion
- [ ] Create `tests/test_search.py` with hybrid search tests
- [ ] Add dependencies to pyproject.toml: lancedb, sentence-transformers, bm25s
- [ ] **CREATE PR**: Push branch, create PR "Phase 1: Conversation Store Foundation", then STOP and wait for review

## Phase 2: Memory Agent — Context Synthesis

- [ ] Create `nanobot/memory/curator.py` with MemoryCurator class
- [ ] Implement MemoryCurator.build_context_packet()
- [ ] Add configurable model selection for curator (default: claude-3-haiku)
- [ ] Implement ReAct loop: search → evaluate → search more or synthesize
- [ ] Add streaming "thinking" output support
- [ ] Create `tests/test_curator.py` with mocked LLM tests
- [ ] Add context packet caching
- [ ] **CREATE PR**: Push branch, create PR "Phase 2: Memory Agent", then STOP and wait for review

## Phase 3: Triage Agent — Fast Path Routing

- [ ] Create `nanobot/memory/triage.py` with TriageAgent class
- [ ] Implement TriageAgent.evaluate() returning TriageResult
- [ ] Add configurable sensitivity slider (1-10)
- [ ] Implement fast-path bypass logic
- [ ] Create `tests/test_triage.py`
- [ ] Add triage decision logging
- [ ] **CREATE PR**: Push branch, create PR "Phase 3: Triage Agent", then STOP and wait for review

## Phase 4: Integration — Wire Into Agent Loop

- [ ] Modify `nanobot/agent/loop.py` to instantiate TriageAgent and MemoryCurator
- [ ] Add triage check before main agent processing
- [ ] Implement "give me a sec" acknowledgment message
- [ ] Modify `nanobot/agent/context.py` to accept context packets
- [ ] Add memory_lookup tool for main agent follow-ups
- [ ] Create integration test: full message flow
- [ ] Add memory config options to config/schema.py
- [ ] **CREATE PR**: Push branch, create PR "Phase 4: Agent Loop Integration", then STOP and wait for review

## Phase 5: Dossiers — Entity Knowledge

- [ ] Create `nanobot/memory/dossier.py` with Dossier dataclass and DossierStore
- [ ] Implement DossierStore CRUD operations
- [ ] Implement DossierStore.search()
- [ ] Add entity extraction in curator
- [ ] Integrate dossier retrieval into context packet building
- [ ] Create `tests/test_dossier.py`
- [ ] Add dossier versioning with timestamps
- [ ] **CREATE PR**: Push branch, create PR "Phase 5: Dossiers", then STOP and wait for review

## Phase 6: Ingestion Pipeline

- [ ] Create `nanobot/memory/ingestion.py` with IngestionPipeline class
- [ ] Implement ingestion hook in agent loop
- [ ] Implement entity extraction from turns
- [ ] Implement dossier update logic
- [ ] Implement new dossier creation for new entities
- [ ] Create `tests/test_ingestion.py`
- [ ] Add background worker for async processing
- [ ] **CREATE PR**: Push branch, create PR "Phase 6: Ingestion Pipeline", then STOP and wait for review

## Phase 7: Streamlined Context

- [ ] Add use_memory_context config option (default: False)
- [ ] Replace full history with system prompt + context packet + last N turns
- [ ] Add topic continuity detection for "last N" selection
- [ ] Add A/B test capability
- [ ] Add metrics logging (context size, retrieval quality)
- [ ] **CREATE PR**: Push branch, create PR "Phase 7: Streamlined Context", then STOP and wait for review

## Phase 8: Documentation and Polish

- [ ] Add comprehensive docstrings to all public APIs
- [ ] Create `docs/memory-architecture.md`
- [ ] Create `docs/configuration.md`
- [ ] Add example scripts for standalone testing
- [ ] Performance profiling and optimization
- [ ] **CREATE PR**: Push branch, create PR "Phase 8: Documentation and Polish", then STOP and wait for review
