"""Qdrant vector database search tool for local knowledge retrieval."""

import json
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool

# ---------------------------------------------------------------------------
# Configuration – keep these at module level so they're easy to tweak later.
# ---------------------------------------------------------------------------
QDRANT_SEARCH_URL = (
    "http://127.0.0.1:6333/collections/jsonify2ai_chunks_768/points/search"
)
SEARCH_LIMIT = 3          # Hard cap to protect local compute resources
REQUEST_TIMEOUT = 30.0    # Seconds


class QdrantSearchTool(Tool):
    """Search the local Qdrant vector store for semantically similar chunks.

    This tool sends a dense-vector similarity query to a local Qdrant
    instance and returns the top-k matching document chunks.
    """

    name = "qdrant_search"
    description = (
        "Search the local Qdrant knowledge base for document chunks that are "
        "semantically similar to a query. Returns the top matching passages."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query_text": {
                "type": "string",
                "description": (
                    "The natural-language search query to find relevant "
                    "document chunks for."
                ),
            },
        },
        "required": ["query_text"],
    }

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------
    async def execute(self, query_text: str, **kwargs: Any) -> str:
        """Run a similarity search against the local Qdrant collection.

        Parameters
        ----------
        query_text : str
            The raw text query to search for.

        Returns
        -------
        str
            JSON-formatted search results, or an error message.
        """

        # ──────────────────────────────────────────────────────────────
        # TODO: EMBEDDING STEP
        # Before we can search Qdrant we need to convert `query_text`
        # into a dense vector (dimension = 768 to match the collection).
        #
        # Future implementation should look roughly like:
        #
        #   query_vector = await embed(query_text)   # -> list[float]
        #
        # For now we raise a clear error so callers know the pipeline
        # is incomplete.
        # ──────────────────────────────────────────────────────────────
        query_vector = self._embed_placeholder(query_text)

        # Build the Qdrant REST search payload
        payload = {
            "vector": query_vector,
            "limit": SEARCH_LIMIT,
            "with_payload": True,
        }

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    QDRANT_SEARCH_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()

            results = response.json().get("result", [])

            if not results:
                return json.dumps(
                    {"query": query_text, "matches": [], "message": "No results found."},
                    ensure_ascii=False,
                )

            # Flatten each hit into a friendlier structure
            matches = []
            for hit in results:
                matches.append({
                    "id": hit.get("id"),
                    "score": hit.get("score"),
                    "payload": hit.get("payload", {}),
                })

            return json.dumps(
                {"query": query_text, "matches": matches},
                ensure_ascii=False,
                indent=2,
            )

        except httpx.HTTPStatusError as exc:
            return json.dumps(
                {
                    "error": f"Qdrant returned HTTP {exc.response.status_code}",
                    "detail": exc.response.text[:500],
                    "query": query_text,
                },
                ensure_ascii=False,
            )
        except httpx.ConnectError:
            return json.dumps(
                {
                    "error": "Could not connect to Qdrant – is it running on 127.0.0.1:6333?",
                    "query": query_text,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"error": str(exc), "query": query_text},
                ensure_ascii=False,
            )

    # ------------------------------------------------------------------
    # Embedding placeholder
    # ------------------------------------------------------------------
    @staticmethod
    def _embed_placeholder(text: str) -> list[float]:
        """Placeholder that returns a zero-vector of the correct dimension.

        ⚠️  Replace this with a real embedding call (e.g. local
        SentenceTransformers, Ollama `/api/embeddings`, or an external
        API) before using this tool in production.

        The collection `jsonify2ai_chunks_768` expects 768-dim vectors.
        """
        # Return a 768-dimensional zero vector so the HTTP call shape is
        # valid even before the real embedding model is wired in.
        return [0.0] * 768
