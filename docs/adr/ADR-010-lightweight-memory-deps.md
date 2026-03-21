# ADR-010: Lightweight Memory Dependencies

## Status
Accepted — 2026-03-21

## Context
The memory subsystem had two heavy optional dependencies:
- sentence-transformers (~500MB+ with PyTorch) for cross-encoder re-ranking
- neo4j (~50MB + external server) for knowledge graph storage

Both had 3-layer fallback patterns that silently disabled functionality when missing.

## Decision
Replace both with lightweight mandatory alternatives:
1. ONNX Runtime cross-encoder (~45MB) as default reranker, with CompositeReranker as config alternative
2. networkx DiGraph (~3MB) with JSON persistence for knowledge graph

## Consequences
### Positive
- Both features always available — no silent degradation
- ~10x smaller install footprint (48MB vs 550MB+)
- No external server needed for graph
- Simpler code — no try/except import guards

### Negative
- ONNX model download on first use (~25MB)
- networkx graph limited to in-process access (single-process only)
- Users with existing Neo4j graphs need one-time migration
