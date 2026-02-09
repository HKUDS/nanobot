# Fix Plan — nanobot Memory Architecture

## Phase 1: Foundation — Conversation Store

- [ ] HIGH: Create `nanobot/memory/__init__.py` with module exports
- [ ] HIGH: Create `nanobot/memory/embedder.py` with Embedder protocol and SentenceTransformerEmbedder implementation
- [ ] HIGH: Create `nanobot/memory/store.py` with Turn dataclass and ConversationStore class using LanceDB
- [ ] HIGH: Implement ConversationStore.add_turn() that embeds and persists a turn with prev/next linking
- [ ] HIGH: Implement ConversationStore.get_turn() and get_thread() for retrieval by ID and thread traversal
- [ ] HIGH: Create `tests/test_store.py` with tests for add, get, and thread traversal
- [ ] MEDIUM: Create `nanobot/memory/search.py` with HybridSearch class combining vector similarity + BM25
- [ ] MEDIUM: Implement HybridSearch.search() returning ranked Turn results with configurable alpha blending
- [ ] MEDIUM: Create `tests/test_search.py` with tests for vector search, BM25 search, and hybrid fusion
- [ ] LOW: Add pyproject.toml dependencies: lancedb, sentence-transformers, bm25s

## Phase 2: Memory Agent — Context Synthesis

- [ ] HIGH: Create `nanobot/memory/curator.py` with MemoryCurator class
- [ ] HIGH: Implement MemoryCurator.build_context_packet() that searches and synthesizes relevant context
- [ ] HIGH: Add configurable model selection for curator (default: claude-3-haiku via litellm)
- [ ] MEDIUM: Implement ReAct loop in curator: search → evaluate relevance → search more or synthesize
- [ ] MEDIUM: Add streaming "thinking" output support for user feedback during memory lookup
- [ ] MEDIUM: Create `tests/test_curator.py` with mocked LLM responses testing synthesis flow
- [ ] LOW: Add context packet caching to avoid redundant synthesis for similar queries

## Phase 3: Triage Agent — Fast Path Routing

- [ ] HIGH: Create `nanobot/memory/triage.py` with TriageAgent class
- [ ] HIGH: Implement TriageAgent.evaluate() returning TriageResult(needs_memory, confidence, quick_response)
- [ ] HIGH: Add configurable sensitivity slider (1-10) affecting memory lookup likelihood
- [ ] MEDIUM: Implement fast-path logic: if needs_memory=False and quick_response exists, skip main agent
- [ ] MEDIUM: Create `tests/test_triage.py` with tests for various message types
- [ ] LOW: Add triage decision logging for later analysis and tuning

## Phase 4: Integration — Wire Into Agent Loop

- [ ] HIGH: Modify `nanobot/agent/loop.py` to instantiate TriageAgent and MemoryCurator
- [ ] HIGH: Add triage check before main agent processing in _process_message()
- [ ] HIGH: Implement "give me a sec" acknowledgment message when memory lookup triggered
- [ ] MEDIUM: Modify `nanobot/agent/context.py` to accept and use context packets from curator
- [ ] MEDIUM: Add memory_lookup tool for main agent to request additional context
- [ ] MEDIUM: Create integration test: message → triage → curator → main agent → response
- [ ] LOW: Add configuration options in config/schema.py for memory system settings

## Phase 5: Dossiers — Entity Knowledge

- [ ] HIGH: Create `nanobot/memory/dossier.py` with Dossier dataclass and DossierStore class
- [ ] HIGH: Implement DossierStore CRUD: create, read, update, delete, list_by_type
- [ ] HIGH: Implement DossierStore.search() for finding relevant dossiers by query
- [ ] MEDIUM: Add entity extraction in curator to identify entities needing dossier lookup
- [ ] MEDIUM: Integrate dossier retrieval into MemoryCurator.build_context_packet()
- [ ] MEDIUM: Create `tests/test_dossier.py` with CRUD and search tests
- [ ] LOW: Add dossier versioning with "as of" timestamps for temporal tracking

## Phase 6: Ingestion Pipeline — Post-Conversation Processing

- [ ] HIGH: Create `nanobot/memory/ingestion.py` with IngestionPipeline class
- [ ] HIGH: Implement ingestion hook in agent loop: after response, queue for processing
- [ ] HIGH: Implement entity extraction from conversation turns
- [ ] MEDIUM: Implement dossier update logic: extract facts, update relevant dossiers
- [ ] MEDIUM: Implement new dossier creation when new entities detected
- [ ] MEDIUM: Create `tests/test_ingestion.py` with entity extraction and dossier update tests
- [ ] LOW: Add background worker for async ingestion processing

## Phase 7: Streamlined Context — Replace Traditional History

- [ ] HIGH: Add configuration option: use_memory_context (bool, default: False for safety)
- [ ] MEDIUM: When enabled, replace full history with: system prompt + context packet + last N turns
- [ ] MEDIUM: Add logic to determine "last N turns" based on topic continuity
- [ ] MEDIUM: Create A/B test capability: traditional vs memory-based context
- [ ] LOW: Add metrics logging: context token count, retrieval quality, response coherence

## Phase 8: Polish and Documentation

- [ ] MEDIUM: Add comprehensive docstrings to all public APIs
- [ ] MEDIUM: Create `docs/memory-architecture.md` with architecture overview
- [ ] MEDIUM: Create `docs/configuration.md` with all memory config options
- [ ] LOW: Add example scripts for testing memory system standalone
- [ ] LOW: Performance profiling and optimization pass
