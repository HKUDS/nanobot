"""Vector memory system backed by Gemini embeddings + Qdrant."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import MemoryConfig
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include concrete, searchable details.",
                    },
                    "memory_facts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "A list of durable facts/preferences/constraints learned from the conversation.",
                    },
                },
                "required": ["history_entry", "memory_facts"],
            },
        },
    }
]


class MemoryStore:
    """Long-term memory in Qdrant using Gemini embeddings."""

    def __init__(self, workspace: Path, config: "MemoryConfig"):
        self.workspace = workspace
        self.config = config
        self._collection_ready = False
        self._vector_size: int | None = None

    def _embedding_runtime_config(self) -> dict[str, Any]:
        """Resolve effective embedding config with backward compatibility."""
        emb = getattr(self.config, "embedding", None)
        if emb and emb.api_key:
            return {
                "provider": emb.provider,
                "api_key": emb.api_key,
                "api_base": emb.api_base,
                "model": emb.model,
                "output_dimensionality": emb.output_dimensionality,
                "timeout_s": emb.timeout_s,
                "extra_headers": dict(emb.extra_headers or {}),
            }

        # Backward compatibility: legacy agents.memory.gemini.*
        gemini = self.config.gemini
        return {
            "provider": "gemini",
            "api_key": gemini.api_key,
            "api_base": gemini.api_base,
            "model": gemini.model,
            "output_dimensionality": gemini.output_dimensionality,
            "timeout_s": gemini.timeout_s,
            "extra_headers": {},
        }

    async def _embed_gemini(
        self, text: str, task_type: str, cfg: dict[str, Any]
    ) -> list[float] | None:
        url = f"{str(cfg['api_base']).rstrip('/')}/{cfg['model']}:embedContent"
        body = {
            "model": cfg["model"],
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": cfg["output_dimensionality"],
        }
        headers = {"x-goog-api-key": cfg["api_key"], "content-type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=int(cfg["timeout_s"])) as client:
                r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 300:
                logger.warning("Gemini embed failed ({}): {}", r.status_code, r.text[:300])
                return None
            data = r.json()
            values = ((data.get("embedding") or {}).get("values") or [])
            if not isinstance(values, list) or not values:
                logger.warning("Gemini embed returned empty vector")
                return None
            return [float(v) for v in values]
        except Exception:
            logger.exception("Gemini embed request failed")
            return None

    async def _embed_openai_compatible(self, text: str, cfg: dict[str, Any]) -> list[float] | None:
        url = f"{str(cfg['api_base']).rstrip('/')}/embeddings"
        body: dict[str, Any] = {"model": cfg["model"], "input": text}
        dim = int(cfg.get("output_dimensionality") or 0)
        if dim > 0:
            body["dimensions"] = dim

        headers = {
            "authorization": f"Bearer {cfg['api_key']}",
            "content-type": "application/json",
            **dict(cfg.get("extra_headers") or {}),
        }

        try:
            async with httpx.AsyncClient(timeout=int(cfg["timeout_s"])) as client:
                r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 300:
                logger.warning("OpenAI-compatible embed failed ({}): {}", r.status_code, r.text[:300])
                return None
            data = r.json()
            items = data.get("data", [])
            if not isinstance(items, list) or not items:
                logger.warning("OpenAI-compatible embed returned empty data")
                return None
            vec = items[0].get("embedding", {})
            if not isinstance(vec, list) or not vec:
                logger.warning("OpenAI-compatible embed returned empty vector")
                return None
            return [float(v) for v in vec]
        except Exception:
            logger.exception("OpenAI-compatible embed request failed")
            return None

    async def _embed(self, text: str, task_type: str) -> list[float] | None:
        text = (text or "").strip()
        if not text:
            return None
        cfg = self._embedding_runtime_config()
        if not cfg["api_key"]:
            logger.warning("Vector memory disabled: embedding api_key is empty")
            return None

        provider = str(cfg["provider"]).lower()
        if provider == "gemini":
            return await self._embed_gemini(text, task_type, cfg)
        if provider == "openai_compatible":
            return await self._embed_openai_compatible(text, cfg)

        logger.warning("Unknown embedding provider '{}'", provider)
        return None

    def _qdrant_headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.config.qdrant.api_key:
            headers["api-key"] = self.config.qdrant.api_key
        return headers

    async def _get_collection_vector_size(self) -> int | None:
        """Return existing collection vector size, or None if unknown."""
        qdrant = self.config.qdrant
        url = f"{qdrant.url.rstrip('/')}/collections/{qdrant.collection}"
        try:
            async with httpx.AsyncClient(timeout=qdrant.timeout_s) as client:
                r = await client.get(url, headers=self._qdrant_headers())
            if r.status_code >= 300:
                return None
            result = (r.json() or {}).get("result", {})
            vectors = ((result.get("config") or {}).get("params") or {}).get("vectors")
            if isinstance(vectors, dict):
                # Single unnamed vector: {"size": 768, "distance": "Cosine"}
                if isinstance(vectors.get("size"), int):
                    return int(vectors["size"])
                # Named vectors: {"text": {"size": 768, ...}, ...}
                for v in vectors.values():
                    if isinstance(v, dict) and isinstance(v.get("size"), int):
                        return int(v["size"])
            return None
        except Exception:
            return None

    async def _ensure_collection(self, vector_size: int) -> bool:
        if self._collection_ready and self._vector_size == vector_size:
            return True

        qdrant = self.config.qdrant
        url = f"{qdrant.url.rstrip('/')}/collections/{qdrant.collection}"
        body = {"vectors": {"size": vector_size, "distance": qdrant.distance}}

        try:
            async with httpx.AsyncClient(timeout=qdrant.timeout_s) as client:
                r = await client.put(url, headers=self._qdrant_headers(), json=body)
            if r.status_code == 409 and "already exists" in r.text.lower():
                existing_size = await self._get_collection_vector_size()
                if existing_size is not None and existing_size != vector_size:
                    logger.warning(
                        "Qdrant collection exists with vector size {}, but embedding size is {}. "
                        "Please recreate collection '{}' or align outputDimensionality.",
                        existing_size, vector_size, qdrant.collection,
                    )
                    return False
                self._collection_ready = True
                self._vector_size = vector_size
                return True
            if r.status_code >= 300:
                logger.warning("Qdrant collection ensure failed ({}): {}", r.status_code, r.text[:300])
                return False
            self._collection_ready = True
            self._vector_size = vector_size
            return True
        except Exception:
            logger.exception("Qdrant collection ensure request failed")
            return False

    async def _upsert_texts(self, texts: list[str], session_key: str, kind: str) -> bool:
        points: list[dict] = []
        for text in texts:
            clean = (text or "").strip()
            if not clean:
                continue
            vector = await self._embed(clean, "RETRIEVAL_DOCUMENT")
            if not vector:
                continue
            if not await self._ensure_collection(len(vector)):
                return False
            points.append({
                "id": str(uuid4()),
                "vector": vector,
                "payload": {
                    "text": clean,
                    "session_key": session_key,
                    "kind": kind,
                    "timestamp": datetime.now().isoformat(),
                },
            })

        if not points:
            return False

        qdrant = self.config.qdrant
        url = f"{qdrant.url.rstrip('/')}/collections/{qdrant.collection}/points?wait=true"
        body = {"points": points}

        try:
            async with httpx.AsyncClient(timeout=qdrant.timeout_s) as client:
                r = await client.put(url, headers=self._qdrant_headers(), json=body)
            if r.status_code >= 300:
                logger.warning("Qdrant upsert failed ({}): {}", r.status_code, r.text[:300])
                return False
            return True
        except Exception:
            logger.exception("Qdrant upsert request failed")
            return False

    async def recall(self, query: str, session_key: str) -> str:
        """Retrieve relevant memory snippets from Qdrant for this session."""
        vector = await self._embed(query, "RETRIEVAL_QUERY")
        if not vector:
            return ""
        if not await self._ensure_collection(len(vector)):
            return ""

        qdrant = self.config.qdrant
        url = f"{qdrant.url.rstrip('/')}/collections/{qdrant.collection}/points/query"
        body: dict[str, object] = {
            "query": vector,
            "limit": max(1, qdrant.top_k),
            "with_payload": True,
            "filter": {
                "must": [
                    {"key": "session_key", "match": {"value": session_key}},
                ]
            },
        }
        if qdrant.score_threshold > 0:
            body["score_threshold"] = qdrant.score_threshold

        try:
            async with httpx.AsyncClient(timeout=qdrant.timeout_s) as client:
                r = await client.post(url, headers=self._qdrant_headers(), json=body)
            if r.status_code >= 300:
                logger.warning("Qdrant query failed ({}): {}", r.status_code, r.text[:300])
                return ""

            data = r.json().get("result", {})
            points = data.get("points") if isinstance(data, dict) else data
            if not isinstance(points, list):
                return ""

            lines = []
            for p in points:
                payload = p.get("payload", {}) if isinstance(p, dict) else {}
                text = (payload.get("text", "") if isinstance(payload, dict) else "").strip()
                if text:
                    lines.append(f"- {text}")
            if not lines:
                return ""
            return "Relevant past memory:\n" + "\n".join(lines)
        except Exception:
            logger.exception("Qdrant query request failed")
            return ""

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Consolidate old messages into vector memory via Gemini embeddings + Qdrant.

        Returns True on success (including no-op), False on failure.
        """
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated:-keep_count]
            if not old_messages:
                return True
            logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")

        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation."},
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
            # Some providers return arguments as a JSON string instead of dict
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            entry = args.get("history_entry", "")
            if not isinstance(entry, str):
                entry = json.dumps(entry, ensure_ascii=False)

            facts = args.get("memory_facts", [])
            if not isinstance(facts, list):
                facts = [json.dumps(facts, ensure_ascii=False)]
            facts = [f if isinstance(f, str) else json.dumps(f, ensure_ascii=False) for f in facts]

            to_store = [entry] + facts
            if to_store and not await self._upsert_texts(to_store, session.key, kind="consolidated"):
                logger.warning("Memory consolidation: failed to write vectors")
                return False

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
