---
name: memory
description: Vector memory system using Gemini embeddings and Qdrant retrieval.
always: true
---

# Memory

## Backend

- Long-term memory is stored as vectors in **Qdrant**.
- Embeddings are generated with **Gemini Embeddings API**.
- Memory retrieval is automatic and injected as context on each new user message.

## What to Store

When consolidating memory, prioritize durable information:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")
- Stable constraints and decisions

## Auto-consolidation

Old conversation turns are automatically summarized, embedded, and upserted to Qdrant when the session grows large. You don't need to manage this manually.
