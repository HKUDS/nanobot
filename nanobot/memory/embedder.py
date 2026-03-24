"""Embedding pipeline — Protocol + OpenAI and local ONNX implementations.

Callers depend on the ``Embedder`` protocol, not concrete classes.
``OpenAIEmbedder`` is the production default; ``LocalEmbedder`` is used
in all tests (no API key needed, 384-dim ONNX model).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Protocol, runtime_checkable

from loguru import logger

__all__ = ["Embedder", "HashEmbedder", "LocalEmbedder", "OpenAIEmbedder"]


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dims(self) -> int: ...

    @property
    def available(self) -> bool: ...


class OpenAIEmbedder:
    """Production embedder using OpenAI text-embedding-3-small (1536 dims).

    Requires OPENAI_API_KEY environment variable.
    """

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self._model = model
        self._dims_value = 1536
        self._client: Any = None
        try:
            import openai

            self._client = openai.AsyncOpenAI()
        except Exception:  # crash-barrier: any OpenAI init failure disables embedder
            logger.warning("OpenAI client not available — embedder disabled")

    @property
    def dims(self) -> int:
        return self._dims_value

    @property
    def available(self) -> bool:
        return self._client is not None

    async def embed(self, text: str) -> list[float]:
        if self._client is None:
            raise RuntimeError("OpenAI client not available — check OPENAI_API_KEY")
        response = await self._client.embeddings.create(model=self._model, input=text)
        result: list[float] = response.data[0].embedding
        return result

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            raise RuntimeError("OpenAI client not available — check OPENAI_API_KEY")
        response = await self._client.embeddings.create(model=self._model, input=texts)
        result: list[list[float]] = [item.embedding for item in response.data]
        return result


class LocalEmbedder:
    """Test embedder using local ONNX model (all-MiniLM-L6-v2, 384 dims).

    Requires onnxruntime and the sentence-transformers model. No API key
    needed. Suitable for contract tests and local development.
    """

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model
        self._dims_value = 384
        self._tokenizer: Any = None
        self._session: Any = None
        self._initialized = False
        self._lock = threading.Lock()

    def _ensure_initialized(self) -> None:
        """Lazy-load the ONNX model on first use."""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            try:
                import onnxruntime as ort
                from huggingface_hub import hf_hub_download
                from tokenizers import Tokenizer

                model_path = hf_hub_download(
                    repo_id=f"sentence-transformers/{self._model_name}",
                    filename="onnx/model.onnx",
                )
                tokenizer_path = hf_hub_download(
                    repo_id=f"sentence-transformers/{self._model_name}",
                    filename="tokenizer.json",
                )
                self._session = ort.InferenceSession(model_path)
                self._tokenizer = Tokenizer.from_file(tokenizer_path)
                self._tokenizer.enable_padding(length=128)
                self._tokenizer.enable_truncation(max_length=128)
                self._initialized = True
            except Exception:  # crash-barrier: ONNX/tokenizer load can fail in many ways
                logger.exception("Failed to load local ONNX embedder")
                raise

    @property
    def dims(self) -> int:
        return self._dims_value

    @property
    def available(self) -> bool:
        try:
            self._ensure_initialized()
            return True
        except Exception:  # crash-barrier: model load failure disables local embedder
            logger.warning("LocalEmbedder not available — model load failed")
            return False

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_initialized()
        import numpy as np

        def _run() -> list[list[float]]:
            encoded = self._tokenizer.encode_batch(texts)
            input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids)
            outputs = self._session.run(
                None,
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "token_type_ids": token_type_ids,
                },
            )
            # Mean pooling over token embeddings
            token_embeddings = outputs[0]  # (batch, seq_len, hidden_dim)
            mask_expanded = np.expand_dims(attention_mask, -1).astype(np.float32)
            summed = np.sum(token_embeddings * mask_expanded, axis=1)
            counts = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
            pooled = summed / counts
            # L2 normalize
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            norms = np.clip(norms, a_min=1e-9, a_max=None)
            normalized = pooled / norms
            result: list[list[float]] = normalized.tolist()
            return result

        return await asyncio.to_thread(_run)


class HashEmbedder:
    """Deterministic hash-based embedder for tests. Zero external dependencies.

    Produces real float vectors from text hashes — sqlite-vec KNN works,
    cosine distance works, but distances are not semantically meaningful.
    Use LocalEmbedder for tests that verify semantic quality.
    """

    def __init__(self, dims: int = 384) -> None:
        self._dims = dims

    @property
    def dims(self) -> int:
        return self._dims

    @property
    def available(self) -> bool:
        return True

    async def embed(self, text: str) -> list[float]:
        return self._hash_to_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_to_vector(t) for t in texts]

    def _hash_to_vector(self, text: str) -> list[float]:
        """Convert text to a deterministic float vector via hashing."""
        import hashlib
        import math
        import struct

        # Generate enough hash bytes for dims floats (4 bytes each)
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # Extend hash by chaining
        result: list[float] = []
        seed = h
        while len(result) < self._dims:
            seed = hashlib.sha256(seed).digest()
            # Unpack 8 floats from 32 bytes
            floats = struct.unpack(f"{len(seed) // 4}f", seed)
            # Replace inf/nan with 0.0 to ensure valid vector components
            result.extend(0.0 if (math.isinf(f) or math.isnan(f)) else f for f in floats)
        # Truncate to exact dims and normalize to unit length
        vec = result[: self._dims]
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec
