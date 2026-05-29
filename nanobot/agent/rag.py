"""Lightweight RAG (Retrieval-Augmented Generation) for memory context.

Inspired by LangChain's RAG patterns but simplified for nanobot:
- In-memory vector store (no external DB dependencies)
- Local embeddings via sentence-transformers (privacy-first)
- Simple recursive text splitter
- Integration with existing MemoryStore

Key components (LangChain-style):
1. Document: Text content with metadata
2. TextSplitter: Recursive character-based splitting
3. Embeddings: Local sentence-transformers
4. VectorStore: In-memory similarity search
5. Retriever: Top-k retrieval interface
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.schema import RAGConfig


@dataclass
class Document:
    """A document with content and metadata (LangChain-style)."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Ensure content is stripped
        self.content = self.content.strip()


class TextSplitter:
    """Recursive character text splitter (LangChain-style).

    Splits text recursively using a hierarchy of separators:
    ["\n\n", "\n", " ", ""]
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        separators: list[str] | None = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", " ", ""]

    def split_text(self, text: str) -> list[str]:
        """Split text into chunks."""
        if not text.strip():
            return []

        # If text is small enough, return as single chunk
        if len(text) <= self.chunk_size:
            return [text.strip()]

        # Try splitting by each separator
        for separator in self.separators:
            if separator in text:
                splits = text.split(separator)
                chunks = self._merge_splits(splits, separator)
                return chunks

        # Fallback: split by character count
        return self._split_by_chars(text)

    def _merge_splits(self, splits: list[str], separator: str) -> list[str]:
        """Merge splits into chunks respecting size limits."""
        chunks = []
        current_chunk = []
        current_size = 0

        for split in splits:
            split_size = len(split) + len(separator) if current_chunk else len(split)

            if current_size + split_size > self.chunk_size and current_chunk:
                # Save current chunk
                chunk_text = separator.join(current_chunk).strip()
                if chunk_text:
                    chunks.append(chunk_text)

                # Start new chunk with overlap
                overlap_text = self._get_overlap(chunks[-1] if chunks else "")
                current_chunk = [overlap_text, split] if overlap_text else [split]
                current_size = len(overlap_text) + len(separator) + len(split) if overlap_text else len(split)
            else:
                current_chunk.append(split)
                current_size += split_size

        # Don't forget the last chunk
        if current_chunk:
            chunk_text = separator.join(current_chunk).strip()
            if chunk_text:
                chunks.append(chunk_text)

        return chunks

    def _get_overlap(self, last_chunk: str) -> str:
        """Get overlap text from the last chunk."""
        if not last_chunk or self.chunk_overlap <= 0:
            return ""

        # Take the last chunk_overlap characters
        overlap = last_chunk[-self.chunk_overlap:]
        # Find a good break point (space or newline)
        for i, char in enumerate(overlap):
            if char in " \n":
                return overlap[i:].strip()
        return overlap.strip()

    def _split_by_chars(self, text: str) -> list[str]:
        """Fallback: split by character count."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - self.chunk_overlap
        return chunks

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """Split documents into smaller chunks."""
        result = []
        for doc in documents:
            chunks = self.split_text(doc.content)
            for i, chunk in enumerate(chunks):
                metadata = doc.metadata.copy()
                metadata["chunk_index"] = i
                result.append(Document(content=chunk, metadata=metadata))
        return result


class Embeddings:
    """Base class for embedding models."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        raise NotImplementedError

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query."""
        raise NotImplementedError


class SentenceTransformerEmbeddings(Embeddings):
    """Local embeddings using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._dimension = None

    def _load_model(self):
        """Lazy load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
                self._dimension = self._model.get_embedding_dimension()
                logger.info(f"Loaded embedding model: {self.model_name} (dim={self._dimension})")
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for RAG. "
                    "Install with: pip install sentence-transformers"
                )
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        model = self._load_model()
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query."""
        return self.embed_documents([query])[0]

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        if self._dimension is None:
            self._load_model()
        return self._dimension


class InMemoryVectorStore:
    """Simple in-memory vector store with cosine similarity search.

    LangChain-style interface: add_documents, similarity_search, similarity_search_with_score.
    """

    def __init__(self, embeddings: Embeddings):
        self.embeddings = embeddings
        self._documents: list[Document] = []
        self._vectors: list[list[float]] = []

    def add_documents(self, documents: list[Document]) -> None:
        """Add documents to the store."""
        if not documents:
            return

        texts = [doc.content for doc in documents]
        vectors = self.embeddings.embed_documents(texts)

        self._documents.extend(documents)
        self._vectors.extend(vectors)
        logger.debug(f"Added {len(documents)} documents to vector store")

    def similarity_search(self, query: str, k: int = 4) -> list[Document]:
        """Search for similar documents."""
        scores = self._similarity_search_with_score(query, k)
        return [doc for doc, _ in scores]

    def similarity_search_with_score(self, query: str, k: int = 4) -> list[tuple[Document, float]]:
        """Search with similarity scores."""
        query_vector = self.embeddings.embed_query(query)
        return self._search_by_vector(query_vector, k)

    def _search_by_vector(self, vector: list[float], k: int = 4) -> list[tuple[Document, float]]:
        """Search by vector using cosine similarity."""
        if not self._vectors:
            return []

        # Compute cosine similarities
        similarities = []
        query_norm = math.sqrt(sum(v * v for v in vector))

        for i, doc_vector in enumerate(self._vectors):
            dot = sum(a * b for a, b in zip(vector, doc_vector))
            doc_norm = math.sqrt(sum(v * v for v in doc_vector))
            similarity = dot / (query_norm * doc_norm) if query_norm > 0 and doc_norm > 0 else 0
            similarities.append((self._documents[i], similarity))

        # Sort by similarity (descending) and return top k
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:k]

    def clear(self) -> None:
        """Clear all documents."""
        self._documents = []
        self._vectors = []

    def __len__(self) -> int:
        """Return number of documents."""
        return len(self._documents)


class VectorStoreRetriever:
    """Retriever interface for vector store (LangChain-style)."""

    def __init__(self, vectorstore: InMemoryVectorStore, k: int = 4, min_score: float = 0.0):
        self.vectorstore = vectorstore
        self.k = k
        self.min_score = min_score

    def invoke(self, query: str) -> list[Document]:
        """Retrieve relevant documents."""
        results = self.vectorstore.similarity_search_with_score(query, self.k)
        return [doc for doc, score in results if score >= self.min_score]

    def get_relevant_context(self, query: str, max_chars: int = 8000) -> str:
        """Get formatted context string for injection."""
        results = self.vectorstore.similarity_search_with_score(query, self.k * 2)

        if not results:
            return ""

        parts = []
        total_chars = 0

        for doc, score in results:
            if score < self.min_score:
                continue
            if total_chars + len(doc.content) > max_chars:
                break

            source = doc.metadata.get("source", "memory")
            timestamp = doc.metadata.get("timestamp", "")
            source_label = f"Memory [{timestamp}]" if timestamp else f"Memory ({source})"

            part = f"[{source_label}] (relevance: {score:.2f})\n{doc.content}"
            parts.append(part)
            total_chars += len(part)

        return "\n\n---\n\n".join(parts)


class RAGPipeline:
    """Complete RAG pipeline: indexing + retrieval.

    Usage:
        pipeline = RAGPipeline(config)
        pipeline.index_documents(docs)
        context = pipeline.retrieve(query)
    """

    def __init__(
        self,
        config: "RAGConfig",
        memory_store: "MemoryStore | None" = None,
    ):
        self.config = config
        self.memory_store = memory_store
        self.splitter = TextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
        self.embeddings = SentenceTransformerEmbeddings(config.embedding_model)
        self.vectorstore = InMemoryVectorStore(self.embeddings)
        self.retriever = VectorStoreRetriever(
            self.vectorstore,
            k=config.top_k,
            min_score=config.min_relevance_score,
        )
        self._indexed = False

    def index_documents(self, documents: list[Document]) -> None:
        """Index documents into the vector store."""
        # Split documents
        split_docs = self.splitter.split_documents(documents)

        # Add to vector store
        self.vectorstore.add_documents(split_docs)
        self._indexed = True

        logger.info(f"Indexed {len(split_docs)} chunks from {len(documents)} documents")

    def index_memory(self) -> None:
        """Index MEMORY.md content."""
        if not self.memory_store:
            logger.warning("No memory store configured")
            return

        content = self.memory_store.read_memory()
        if not content.strip():
            logger.debug("MEMORY.md is empty")
            return

        doc = Document(
            content=content,
            metadata={"source": "memory", "type": "long_term"},
        )
        self.index_documents([doc])

    def index_history(self) -> None:
        """Index history.jsonl entries."""
        if not self.memory_store:
            return

        entries = self.memory_store.read_unprocessed_history(since_cursor=0)
        if not entries:
            return

        documents = []
        for entry in entries:
            content = entry.get("content", "")
            if not content.strip():
                continue

            doc = Document(
                content=content,
                metadata={
                    "source": "history",
                    "type": "conversation",
                    "cursor": entry.get("cursor"),
                    "timestamp": entry.get("timestamp"),
                },
            )
            documents.append(doc)

        self.index_documents(documents)

    def index_all(self) -> None:
        """Index all memory content."""
        self.vectorstore.clear()
        self.index_memory()
        self.index_history()

    def retrieve(self, query: str, max_chars: int | None = None) -> str:
        """Retrieve relevant context for a query."""
        if not self._indexed:
            logger.warning("RAG pipeline not indexed, indexing now...")
            self.index_all()

        max_chars = max_chars or self.config.max_context_chars
        return self.retriever.get_relevant_context(query, max_chars)

    def search(self, query: str, k: int | None = None) -> list[tuple[Document, float]]:
        """Search for relevant documents with scores."""
        if not self._indexed:
            self.index_all()

        k = k or self.config.top_k
        return self.vectorstore.similarity_search_with_score(query, k)

    def get_stats(self) -> dict[str, Any]:
        """Get pipeline statistics."""
        return {
            "enabled": self.config.enabled,
            "indexed": self._indexed,
            "model": self.config.embedding_model,
            "total_chunks": len(self.vectorstore),
            "chunk_size": self.config.chunk_size,
            "top_k": self.config.top_k,
        }


def create_rag_pipeline(
    config: "RAGConfig",
    memory_store: "MemoryStore | None" = None,
) -> RAGPipeline | None:
    """Factory function to create RAG pipeline if enabled."""
    if not config.enabled:
        return None

    try:
        return RAGPipeline(config, memory_store)
    except ImportError as e:
        logger.warning(f"RAG disabled: {e}")
        return None