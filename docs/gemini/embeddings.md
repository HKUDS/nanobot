1# Embeddings

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/embeddings

## What It Is

Generate high-dimensional vector representations of text for semantic search, classification, clustering, and RAG.

## Gemini API Capabilities

### Model

`gemini-embedding-001`

### Dimensions

- Default: 3,072
- Supported range: 128–3,072 (Matryoshka Representation Learning)
- Recommended: 768, 1,536, or 3,072
- 3,072 output is normalized; smaller dimensions need manual normalization

### Token limits

- Input: 2,048 tokens per request
- Batch processing supported

### Task types (8)

| Type | Use case |
|------|----------|
| SEMANTIC_SIMILARITY | Text similarity assessment |
| CLASSIFICATION | Text categorization |
| CLUSTERING | Grouping by similarity |
| RETRIEVAL_DOCUMENT | Document indexing |
| RETRIEVAL_QUERY | General search queries |
| CODE_RETRIEVAL_QUERY | Code block retrieval |
| QUESTION_ANSWERING | Question-document matching |
| FACT_VERIFICATION | Evidence retrieval |

### Batch API support

50% discount via Batch API for high-throughput embedding.

### Vector DB integrations

BigQuery, AlloyDB, Cloud SQL, ChromaDB, QDrant, Weaviate, Pinecone

## Nanobot Implementation

Not implemented. Memory system is text-based session history, not vector embeddings.

**What embeddings would enable:**
- Semantic memory search (find relevant past conversations)
- Document indexing for workspace files
- RAG pipeline without external embedding service
- Clustering/classification of conversations
