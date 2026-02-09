# WORKPLAN — nanobot Memory Architecture

## Phase 1: Foundation — Conversation Store

- [ ] Create `nanobot/memory/__init__.py` with module exports
- [ ] Create `nanobot/memory/embedder.py` with Embedder protocol and SentenceTransformerEmbedder <!-- slice:memory, touches:none -->
- [ ] Create `nanobot/memory/store.py` with Turn dataclass and ConversationStore class <!-- slice:memory, touches:none -->
- [ ] Implement ConversationStore.add_turn() with embedding and prev/next linking <!-- slice:memory, touches:embedder -->
- [ ] Implement ConversationStore.get_turn() and get_thread() <!-- slice:memory, touches:none -->
- [ ] Create `tests/test_store.py` with add, get, and thread traversal tests <!-- slice:memory, touches:none -->
- [ ] Create `nanobot/memory/search.py` with HybridSearch class <!-- slice:memory, touches:store -->
- [ ] Implement HybridSearch.search() with vector + BM25 fusion <!-- slice:memory, touches:embedder -->
- [ ] Create `tests/test_search.py` with hybrid search tests <!-- slice:memory, touches:none -->
- [ ] Add dependencies to pyproject.toml: lancedb, sentence-transformers, bm25s <!-- slice:config, touches:none -->

## Phase 2: Memory Agent — Context Synthesis

- [ ] Create `nanobot/memory/curator.py` with MemoryCurator class <!-- slice:memory, touches:search,store -->
- [ ] Implement MemoryCurator.build_context_packet() <!-- slice:memory, touches:search -->
- [ ] Add configurable model selection for curator (default: claude-3-haiku) <!-- slice:memory, touches:providers -->
- [ ] Implement ReAct loop: search → evaluate → search more or synthesize <!-- slice:memory, touches:search -->
- [ ] Add streaming "thinking" output support <!-- slice:memory, touches:none -->
- [ ] Create `tests/test_curator.py` with mocked LLM tests <!-- slice:memory, touches:none -->
- [ ] Add context packet caching <!-- slice:memory, touches:none -->

## Phase 3: Triage Agent — Fast Path Routing

- [ ] Create `nanobot/memory/triage.py` with TriageAgent class <!-- slice:memory, touches:none -->
- [ ] Implement TriageAgent.evaluate() returning TriageResult <!-- slice:memory, touches:providers -->
- [ ] Add configurable sensitivity slider (1-10) <!-- slice:memory, touches:config -->
- [ ] Implement fast-path bypass logic <!-- slice:memory, touches:none -->
- [ ] Create `tests/test_triage.py` <!-- slice:memory, touches:none -->
- [ ] Add triage decision logging <!-- slice:memory, touches:none -->

## Phase 4: Integration — Wire Into Agent Loop

- [ ] Modify `nanobot/agent/loop.py` to instantiate TriageAgent and MemoryCurator <!-- slice:agent, touches:memory -->
- [ ] Add triage check before main agent processing <!-- slice:agent, touches:memory -->
- [ ] Implement "give me a sec" acknowledgment message <!-- slice:agent, touches:channels -->
- [ ] Modify `nanobot/agent/context.py` to accept context packets <!-- slice:agent, touches:memory -->
- [ ] Add memory_lookup tool for main agent follow-ups <!-- slice:agent, touches:memory -->
- [ ] Create integration test: full message flow <!-- slice:agent, touches:memory -->
- [ ] Add memory config options to config/schema.py <!-- slice:config, touches:none -->

## Phase 5: Dossiers — Entity Knowledge

- [ ] Create `nanobot/memory/dossier.py` with Dossier dataclass and DossierStore <!-- slice:memory, touches:store -->
- [ ] Implement DossierStore CRUD operations <!-- slice:memory, touches:none -->
- [ ] Implement DossierStore.search() <!-- slice:memory, touches:search -->
- [ ] Add entity extraction in curator <!-- slice:memory, touches:curator -->
- [ ] Integrate dossier retrieval into context packet building <!-- slice:memory, touches:curator -->
- [ ] Create `tests/test_dossier.py` <!-- slice:memory, touches:none -->
- [ ] Add dossier versioning with timestamps <!-- slice:memory, touches:none -->

## Phase 6: Ingestion Pipeline

- [ ] Create `nanobot/memory/ingestion.py` with IngestionPipeline class <!-- slice:memory, touches:store,dossier -->
- [ ] Implement ingestion hook in agent loop <!-- slice:agent, touches:memory -->
- [ ] Implement entity extraction from turns <!-- slice:memory, touches:none -->
- [ ] Implement dossier update logic <!-- slice:memory, touches:dossier -->
- [ ] Implement new dossier creation for new entities <!-- slice:memory, touches:dossier -->
- [ ] Create `tests/test_ingestion.py` <!-- slice:memory, touches:none -->
- [ ] Add background worker for async processing <!-- slice:memory, touches:none -->

## Phase 7: Streamlined Context

- [ ] Add use_memory_context config option (default: False) <!-- slice:config, touches:none -->
- [ ] Replace full history with system prompt + context packet + last N turns <!-- slice:agent, touches:context -->
- [ ] Add topic continuity detection for "last N" selection <!-- slice:agent, touches:memory -->
- [ ] Add A/B test capability <!-- slice:agent, touches:config -->
- [ ] Add metrics logging (context size, retrieval quality) <!-- slice:agent, touches:none -->

## Phase 8: Documentation and Polish

- [ ] Add comprehensive docstrings to all public APIs <!-- slice:memory, touches:none -->
- [ ] Create `docs/memory-architecture.md` <!-- slice:docs, touches:none -->
- [ ] Create `docs/configuration.md` <!-- slice:docs, touches:none -->
- [ ] Add example scripts for standalone testing <!-- slice:docs, touches:none -->
- [ ] Performance profiling and optimization <!-- slice:memory, touches:none -->
