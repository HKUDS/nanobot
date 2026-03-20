"""Thin compatibility wrapper around mem0 OSS/hosted clients."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from mem0 import Memory as Mem0Memory
except Exception:  # crash-barrier: mem0 SDK  # pragma: no cover - optional dependency
    Mem0Memory = None

try:
    from mem0 import MemoryClient as Mem0MemoryClient
except Exception:  # crash-barrier: mem0 SDK  # pragma: no cover - optional dependency
    Mem0MemoryClient = None


class _Mem0Adapter:
    """Thin compatibility wrapper around mem0 OSS/hosted clients."""

    def __init__(
        self,
        *,
        workspace: Path,
        user_id: str = "nanobot",
        add_debug: bool = False,
        verify_write: bool = True,
        force_infer_true: bool = False,
    ):
        self.workspace = workspace
        self.user_id = user_id
        self.enabled = False
        self.client: Any | None = None
        self.mode = "disabled"
        self.error: str | None = None
        self._add_debug = add_debug
        self._verify_write = verify_write
        self._force_infer_true = force_infer_true
        self._local_fallback_attempted = False
        self._local_mem0_dir: Path | None = None
        self._fallback_enabled = True
        self._fallback_candidates: list[tuple[str, dict[str, Any], int]] = [
            ("huggingface", {"model": "sentence-transformers/all-MiniLM-L6-v2"}, 384),
        ]
        self.last_add_mode = "unknown"
        self._infer_true_disabled = False
        self._infer_true_disable_reason = ""
        self._init_client()

    def _load_fallback_config(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        fallback = payload.get("fallback")
        if not isinstance(fallback, dict):
            return {}
        enabled = fallback.get("enabled")
        if isinstance(enabled, bool):
            self._fallback_enabled = enabled

        providers = fallback.get("providers")
        parsed: list[tuple[str, dict[str, Any], int]] = []
        if isinstance(providers, list):
            for item in providers:
                if not isinstance(item, dict):
                    continue
                provider = str(item.get("provider", "")).strip().lower()
                if not provider:
                    continue
                _raw_config = item.get("config")
                config: dict[str, Any] = _raw_config if isinstance(_raw_config, dict) else {}
                dims_raw = item.get("embedding_model_dims", 384)
                try:
                    dims = int(dims_raw)
                except (TypeError, ValueError):
                    dims = 384
                parsed.append((provider, config, max(1, dims)))
        if parsed:
            self._fallback_candidates = parsed
        return fallback

    @staticmethod
    def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            return None
        key, value = text.split("=", 1)
        key = key.strip()
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            return None
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        return key, value

    def _load_env_candidates(self) -> None:
        candidates = [
            self.workspace / ".env",
        ]
        seen: set[Path] = set()
        for path in candidates:
            try:
                p = path.expanduser().resolve()
            except (OSError, ValueError):
                p = path
            if p in seen or not p.exists() or not p.is_file():
                continue
            seen.add(p)
            try:
                for raw in p.read_text(encoding="utf-8").splitlines():
                    parsed = self._parse_dotenv_line(raw)
                    if not parsed:
                        continue
                    key, value = parsed
                    os.environ.setdefault(key, value)
            except (OSError, UnicodeDecodeError):
                continue
        # Also load provider API keys from nanobot config.json so mem0 can use them.
        self._load_api_keys_from_config()

    _ENV_KEY_MAP: dict[str, str] = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "groq": "GROQ_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }

    def _load_api_keys_from_config(self) -> None:
        """Extract provider API keys from ~/.nanobot/config.json into env vars."""
        config_path = Path.home() / ".nanobot" / "config.json"
        if not config_path.exists():
            return
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        providers = cfg.get("providers")
        if not isinstance(providers, dict):
            return
        for name, env_key in self._ENV_KEY_MAP.items():
            prov = providers.get(name)
            if isinstance(prov, dict):
                # Config may use camelCase (apiKey) or snake_case (api_key)
                key = prov.get("api_key", "") or prov.get("apiKey", "")
                if key:
                    os.environ.setdefault(env_key, key)

    @staticmethod
    def _build_llm_config() -> dict[str, Any]:
        """Build a mem0 LLM config using litellm (inherits env vars set by nanobot)."""
        return {"provider": "litellm", "config": {"model": "openai/gpt-4o-mini"}}

    def _init_client(self) -> None:
        self._load_env_candidates()
        config_path = self.workspace / "memory" / "mem0_config.json"
        local_mem0_dir = self.workspace / "memory" / "mem0"
        local_mem0_dir.mkdir(parents=True, exist_ok=True)
        self._local_mem0_dir = local_mem0_dir
        os.environ.setdefault("MEM0_DIR", str(local_mem0_dir))
        try:
            import mem0.configs.base as mem0_base
            import mem0.memory.main as mem0_main
            import mem0.memory.setup as mem0_setup

            mem0_base.mem0_dir = str(local_mem0_dir)
            mem0_setup.mem0_dir = str(local_mem0_dir)
            mem0_main.mem0_dir = str(local_mem0_dir)
        except Exception:  # crash-barrier: mem0 SDK
            pass
        api_key = os.getenv("MEM0_API_KEY", "").strip()

        if api_key and Mem0MemoryClient is not None:
            try:
                org_id = os.getenv("MEM0_ORG_ID", "").strip() or None
                project_id = os.getenv("MEM0_PROJECT_ID", "").strip() or None
                kwargs: dict[str, Any] = {"api_key": api_key}
                if org_id:
                    kwargs["org_id"] = org_id
                if project_id:
                    kwargs["project_id"] = project_id
                self.client = Mem0MemoryClient(**kwargs)
                self.enabled = True
                self.mode = "hosted"
                return
            except Exception as exc:  # crash-barrier: mem0 SDK
                self.error = str(exc)

        if Mem0Memory is None:
            self.error = self.error or "mem0 package not installed"
            return

        payload: dict[str, Any] | None = None
        if config_path.exists():
            try:
                loaded = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, json.JSONDecodeError):
                payload = None
        self._load_fallback_config(payload)

        def _ensure_local_qdrant_on_disk(config_payload: dict[str, Any]) -> dict[str, Any]:
            out = dict(config_payload)
            vector_store = out.get("vector_store")
            if not isinstance(vector_store, dict):
                return out
            provider = str(vector_store.get("provider", "")).strip().lower()
            if provider != "qdrant":
                return out
            vs_cfg = dict(vector_store.get("config") or {})
            # For local qdrant path mode in mem0>=1.0.4, on_disk must be true or data can be reset.
            if str(vs_cfg.get("path", "")).strip():
                vs_cfg["on_disk"] = True
            vector_store["config"] = vs_cfg
            out["vector_store"] = vector_store
            return out

        try:
            if payload is not None:
                mem0_payload = dict(payload)
                mem0_payload.pop("fallback", None)
                mem0_payload = _ensure_local_qdrant_on_disk(mem0_payload)
                self.client = Mem0Memory.from_config(mem0_payload)
            else:
                # Force local writable persistence instead of ~/.mem0/*
                self.client = Mem0Memory.from_config(
                    {
                        "llm": self._build_llm_config(),
                        "history_db_path": str(local_mem0_dir / "history.db"),
                        "vector_store": {
                            "provider": "qdrant",
                            "config": {
                                "collection_name": "nanobot_mem0",
                                "path": str(local_mem0_dir / "qdrant"),
                                "on_disk": True,
                            },
                        },
                    }
                )
            self.enabled = True
            self.mode = "oss"
            return
        except Exception as exc:  # crash-barrier: mem0 SDK
            if self._activate_local_fallback(reason=f"initialization failed: {exc}"):
                return
            self.error = str(exc)
            self.enabled = False
            self.client = None
            self.mode = "disabled"
            logger.warning("mem0 disabled: {}", self.error)

    def _activate_local_fallback(self, *, reason: str) -> bool:
        if self._local_fallback_attempted or Mem0Memory is None:
            return False
        if not self._fallback_enabled:
            return False
        if self.mode == "hosted":
            return False
        self._local_fallback_attempted = True
        local_mem0_dir = self._local_mem0_dir or (self.workspace / "memory" / "mem0")
        local_mem0_dir.mkdir(parents=True, exist_ok=True)

        for provider, embedder_cfg, dims in self._fallback_candidates:
            try:
                self.client = Mem0Memory.from_config(
                    {
                        "llm": self._build_llm_config(),
                        "embedder": {"provider": provider, "config": embedder_cfg},
                        "vector_store": {
                            "provider": "qdrant",
                            "config": {
                                "collection_name": f"nanobot_mem0_local_{provider}",
                                "path": str(local_mem0_dir / "qdrant"),
                                "embedding_model_dims": dims,
                                "on_disk": True,
                            },
                        },
                        "history_db_path": str(local_mem0_dir / "history.db"),
                    }
                )
                self.enabled = True
                self.mode = f"oss-local-fallback-{provider}"
                self.error = None
                logger.warning(
                    "mem0 switched to local fallback embedder ({}): {}", provider, reason
                )
                return True
            except Exception as exc:  # crash-barrier: mem0 SDK
                self.error = str(exc)
                logger.warning("mem0 local fallback ({}) failed: {}", provider, self.error)
                continue
        return False

    @staticmethod
    def _rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            for key in ("results", "data", "memories"):
                rows = payload.get(key)
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)]
        return []

    def get_all_count(self, *, limit: int = 200) -> int:
        if not self.enabled or not self.client:
            return 0
        try:
            raw = self.client.get_all(user_id=self.user_id, limit=max(1, limit))
        except TypeError:
            try:
                raw = self.client.get_all(self.user_id, max(1, limit))
            except Exception:  # crash-barrier: mem0 SDK
                return 0
        except Exception:  # crash-barrier: mem0 SDK
            return 0
        return len(self._rows(raw))

    def flush_vector_store(self) -> bool:
        if not self.client:
            return False
        try:
            vector_store = getattr(self.client, "vector_store", None)
            if vector_store is None:
                return False
            vector_client = getattr(vector_store, "client", None)
            if vector_client is None or not hasattr(vector_client, "close"):
                return False
            vector_client.close()
            return True
        except Exception:  # crash-barrier: mem0 SDK
            return False

    def reopen_client(self) -> None:
        self.enabled = False
        self.client = None
        self.mode = "disabled"
        self.error = None
        self._local_fallback_attempted = False
        self._init_client()

    def delete_all_user_memories(self) -> tuple[bool, str, int]:
        """Delete all memories for current user_id. Returns (ok, reason, deleted_estimate)."""
        if not self.enabled or not self.client:
            return False, "mem0_disabled", 0
        before = self.get_all_count(limit=5000)
        try:
            self.client.delete_all(user_id=self.user_id)
            return True, "delete_all_user_id", before
        except TypeError:
            try:
                self.client.delete_all(self.user_id)
                return True, "delete_all_positional_user_id", before
            except Exception as exc:  # crash-barrier: mem0 SDK
                return False, f"delete_all_failed:{exc}", 0
        except Exception as exc:  # crash-barrier: mem0 SDK
            return False, f"delete_all_failed:{exc}", 0

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {tok for tok in re.findall(r"[a-z0-9]+", text.lower()) if len(tok) >= 2}

    @classmethod
    def _lexical_score(cls, query: str, candidate: str) -> float:
        q = cls._tokenize(query)
        c = cls._tokenize(candidate)
        if not q or not c:
            return 0.0
        overlap = len(q & c)
        if overlap <= 0:
            return 0.0
        return overlap / max(len(q), 1)

    def _row_to_item(
        self, item: dict[str, Any], *, fallback_score: float | None = None
    ) -> dict[str, Any] | None:
        summary = str(item.get("memory") or item.get("text") or item.get("summary") or "").strip()
        if not summary:
            return None
        _raw_meta = item.get("metadata")
        metadata: dict[str, Any] = _raw_meta if isinstance(_raw_meta, dict) else {}
        memory_type = str(metadata.get("memory_type", "episodic")).strip().lower() or "episodic"
        if memory_type not in {"semantic", "episodic", "reflection"}:
            memory_type = "episodic"
        stability = str(metadata.get("stability", "medium")).strip().lower() or "medium"
        if stability not in {"high", "medium", "low"}:
            stability = "medium"
        source = str(metadata.get("source", "chat")).strip().lower() or "chat"
        topic = str(metadata.get("topic", "general")).strip() or "general"
        confidence_raw = metadata.get("confidence")
        try:
            confidence = min(
                max(float(confidence_raw if confidence_raw is not None else 0.7), 0.0), 1.0
            )
        except (TypeError, ValueError):
            confidence = 0.7
        evidence_refs = metadata.get("evidence_refs")
        if not isinstance(evidence_refs, list):
            evidence_refs = []
        evidence_refs = [str(x).strip() for x in evidence_refs if str(x).strip()]
        timestamp = (
            item.get("updated_at") or item.get("created_at") or metadata.get("timestamp") or ""
        )
        event_type = str(metadata.get("event_type", "fact"))
        raw_score = item.get("score", 0.0)
        try:
            score = float(raw_score if raw_score is not None else 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if fallback_score is not None:
            score = max(score, fallback_score)
        canonical_id = str(item.get("id") or hashlib.sha1(summary.encode("utf-8")).hexdigest())
        return {
            "id": canonical_id,
            "timestamp": str(timestamp),
            "type": event_type,
            "summary": summary,
            "entities": metadata.get("entities", []),
            "score": score,
            "memory_type": memory_type,
            "topic": topic,
            "stability": stability,
            "source": source,
            "confidence": confidence,
            "evidence_refs": evidence_refs,
            "retrieval_reason": {
                "provider": "mem0",
                "backend": "mem0",
                "semantic": round(score, 4),
                "recency": 0.0,
            },
            "provenance": {
                "canonical_id": canonical_id,
                "source_span": metadata.get("source_span"),
            },
        }

    @staticmethod
    def _looks_blob_like_summary(summary: str) -> bool:
        text = str(summary or "").strip().lower()
        if not text:
            return True
        markers = ("[runtime context]", "/home/", ".jsonl:", "```", "# memory", "## ")
        if any(marker in text for marker in markers):
            return True
        return summary.count("\n") >= 4

    def _fallback_search_via_get_all(
        self,
        query: str,
        *,
        top_k: int,
        allowed_sources: set[str] | None = None,
        max_summary_chars: int = 280,
        reject_blob_like: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        if not self.client:
            return [], 0
        try:
            raw = self.client.get_all(user_id=self.user_id, limit=max(100, top_k * 25))
        except TypeError:
            try:
                raw = self.client.get_all(self.user_id, max(100, top_k * 25))
            except Exception:  # crash-barrier: mem0 SDK
                return [], 0
        except Exception:  # crash-barrier: mem0 SDK
            return [], 0

        ranked: list[tuple[float, dict[str, Any]]] = []
        rejected_blob_like = 0
        seen_norm: set[str] = set()
        for item in self._rows(raw):
            summary = str(
                item.get("memory") or item.get("text") or item.get("summary") or ""
            ).strip()
            if not summary:
                continue
            if len(summary) > max_summary_chars:
                continue
            _raw_meta = item.get("metadata")
            metadata: dict[str, Any] = _raw_meta if isinstance(_raw_meta, dict) else {}
            source = str(metadata.get("source", "mem0_get_all")).strip().lower() or "mem0_get_all"
            if (
                isinstance(allowed_sources, set)
                and allowed_sources
                and source not in allowed_sources
            ):
                continue
            if reject_blob_like and self._looks_blob_like_summary(summary):
                rejected_blob_like += 1
                continue
            lexical = self._lexical_score(query, summary)
            if lexical <= 0:
                continue
            normalized = self._row_to_item(item, fallback_score=lexical)
            if normalized is None:
                continue
            normalized["source"] = source
            normalized_reason = normalized.get("retrieval_reason")
            if isinstance(normalized_reason, dict):
                normalized_reason["backend"] = "mem0_get_all"
            norm_key = re.sub(r"\s+", " ", summary.strip().lower())
            if norm_key in seen_norm:
                continue
            seen_norm.add(norm_key)
            ranked.append((lexical, normalized))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[: max(1, top_k)]], rejected_blob_like

    @staticmethod
    def _history_memory_type(summary: str) -> str:
        text = summary.lower()
        if any(
            token in text
            for token in (
                "failed",
                "error",
                "incident",
                "tried",
                "attempt",
                "resolved",
                "yesterday",
            )
        ):
            return "episodic"
        if any(
            token in text
            for token in ("prefer", "always", "never", "must", "cannot", "user", "setup", "uses")
        ):
            return "semantic"
        return "semantic"

    def _fallback_search_via_history_db(
        self,
        query: str,
        *,
        top_k: int,
        max_summary_chars: int = 280,
        reject_blob_like: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        if not self._local_mem0_dir:
            return [], 0
        history_db = self._local_mem0_dir / "history.db"
        if not history_db.exists():
            return [], 0
        try:
            conn = sqlite3.connect(history_db)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT memory_id, new_memory, created_at, event
                FROM history
                WHERE COALESCE(is_deleted, 0) = 0
                  AND COALESCE(new_memory, '') != ''
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(200, top_k * 40),),
            )
            rows = cur.fetchall()
            conn.close()
        except (sqlite3.Error, OSError):
            return [], 0

        ranked: list[tuple[float, dict[str, Any]]] = []
        rejected_blob_like = 0
        seen_norm: set[str] = set()
        for memory_id, text, created_at, event in rows:
            summary = str(text or "").strip()
            if not summary:
                continue
            if len(summary) > max_summary_chars:
                continue
            if reject_blob_like and self._looks_blob_like_summary(summary):
                rejected_blob_like += 1
                continue
            lexical = self._lexical_score(query, summary)
            if lexical <= 0:
                continue
            memory_type = self._history_memory_type(summary)
            item = {
                "id": str(memory_id or hashlib.sha1(summary.encode("utf-8")).hexdigest()),
                "timestamp": str(created_at or ""),
                "type": "fact",
                "summary": summary,
                "entities": [],
                "score": lexical,
                "memory_type": memory_type,
                "topic": "history",
                "stability": "medium" if memory_type == "episodic" else "high",
                "source": "history_db",
                "confidence": 0.6,
                "evidence_refs": [],
                "retrieval_reason": {
                    "provider": "mem0",
                    "backend": "history_db_fallback",
                    "semantic": round(lexical, 4),
                    "recency": 0.0,
                },
                "provenance": {
                    "canonical_id": str(memory_id or ""),
                    "source_span": None,
                    "event": str(event or ""),
                },
            }
            norm_key = re.sub(r"\s+", " ", summary.strip().lower())
            if norm_key in seen_norm:
                continue
            seen_norm.add(norm_key)
            ranked.append((lexical, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[: max(1, top_k)]], rejected_blob_like

    def add_text(self, text: str, *, metadata: dict[str, Any] | None = None) -> bool:
        if not self.enabled or not self.client or not text.strip():
            return False
        messages = [{"role": "user", "content": text.strip()}]
        kwargs: dict[str, Any] = {"user_id": self.user_id}
        if metadata:
            kwargs["metadata"] = metadata
        add_debug = self._add_debug
        verify_write = self._verify_write
        force_infer_true = self._force_infer_true
        before_count = self.get_all_count(limit=200) if verify_write or add_debug else -1

        def _is_infer_true_disabled_error(exc: Exception) -> bool:
            text = str(exc).lower()
            markers = (
                "insufficient_quota",
                "exceeded your current quota",
                "rate limit",
                "rate_limit",
                "invalid api key",
                "authentication",
                "unauthorized",
                "api key",
            )
            return any(marker in text for marker in markers)

        def _attempt(mode: str, fn: Any) -> bool:
            try:
                fn()
            except Exception as exc:  # crash-barrier: mem0 SDK
                if mode.startswith("infer_true") and _is_infer_true_disabled_error(exc):
                    self._infer_true_disabled = True
                    self._infer_true_disable_reason = str(exc)
                    if add_debug:
                        logger.debug(
                            "mem0 infer_true disabled due to compatibility error: {}",
                            self._infer_true_disable_reason,
                        )
                return False
            self.last_add_mode = mode
            after_count = self.get_all_count(limit=200) if verify_write or add_debug else -1
            if add_debug:
                logger.debug(
                    "mem0 add_text mode={} before={} after={}", mode, before_count, after_count
                )
            if verify_write and after_count <= before_count:
                return False
            return True

        infer_true_allowed = force_infer_true or (
            self.mode == "hosted" and not self._infer_true_disabled
        )
        if infer_true_allowed:
            # Hosted mem0 can usually use infer=True end to end.
            if _attempt("infer_true", lambda: self.client.add(messages, infer=True, **kwargs)):
                return True
            # Fallback for older hosted client signatures.
            if _attempt("default_signature", lambda: self.client.add(messages, **kwargs)):
                return True
            if _attempt(
                "infer_false_fallback", lambda: self.client.add(messages, infer=False, **kwargs)
            ):
                return True
        else:
            # OSS/local mem0 path: prefer infer=False to avoid LLM quota/auth coupling.
            if _attempt(
                "infer_false_primary", lambda: self.client.add(messages, infer=False, **kwargs)
            ):
                return True
            if force_infer_true and _attempt(
                "infer_true_forced", lambda: self.client.add(messages, infer=True, **kwargs)
            ):
                return True
            if _attempt("default_signature_fallback", lambda: self.client.add(messages, **kwargs)):
                return True

        if (
            self._activate_local_fallback(reason="add_text write verification failed")
            and self.client
        ):
            if _attempt(
                "infer_false_local_fallback",
                lambda: self.client.add(messages, infer=False, **kwargs),
            ):
                return True
            if force_infer_true and _attempt(
                "infer_true_local_forced", lambda: self.client.add(messages, infer=True, **kwargs)
            ):
                return True
            if _attempt(
                "default_signature_local_fallback", lambda: self.client.add(messages, **kwargs)
            ):
                return True
        return False

    def search(
        self,
        query: str,
        *,
        top_k: int = 6,
        allow_get_all_fallback: bool = True,
        allow_history_fallback: bool = False,
        allowed_sources: set[str] | None = None,
        max_summary_chars: int = 280,
        reject_blob_like: bool = True,
        return_stats: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, int]]:
        if not self.enabled or not self.client or not query.strip():
            empty_stats = {
                "source_vector": 0,
                "source_get_all": 0,
                "source_history": 0,
                "rejected_blob_like": 0,
            }
            return ([], empty_stats) if return_stats else []
        kwargs: dict[str, Any] = {"user_id": self.user_id, "limit": max(1, top_k)}
        try:
            raw = self.client.search(query=query, **kwargs)
        except TypeError:
            try:
                raw = self.client.search(query, **kwargs)
            except Exception:  # crash-barrier: mem0 SDK
                empty_stats = {
                    "source_vector": 0,
                    "source_get_all": 0,
                    "source_history": 0,
                    "rejected_blob_like": 0,
                }
                return ([], empty_stats) if return_stats else []
        except Exception as exc:  # crash-barrier: mem0 SDK
            if self._activate_local_fallback(reason=f"search failed: {exc}") and self.client:
                try:
                    raw = self.client.search(query=query, **kwargs)
                except TypeError:
                    try:
                        raw = self.client.search(query, **kwargs)
                    except Exception:  # crash-barrier: mem0 SDK
                        empty_stats = {
                            "source_vector": 0,
                            "source_get_all": 0,
                            "source_history": 0,
                            "rejected_blob_like": 0,
                        }
                        return ([], empty_stats) if return_stats else []
                except Exception:  # crash-barrier: mem0 SDK
                    empty_stats = {
                        "source_vector": 0,
                        "source_get_all": 0,
                        "source_history": 0,
                        "rejected_blob_like": 0,
                    }
                    return ([], empty_stats) if return_stats else []
            else:
                empty_stats = {
                    "source_vector": 0,
                    "source_get_all": 0,
                    "source_history": 0,
                    "rejected_blob_like": 0,
                }
                return ([], empty_stats) if return_stats else []

        out: list[dict[str, Any]] = []
        source_counts = {
            "source_vector": 0,
            "source_get_all": 0,
            "source_history": 0,
            "rejected_blob_like": 0,
        }
        for item in self._rows(raw):
            normalized = self._row_to_item(item)
            if normalized is not None:
                if isinstance(normalized.get("retrieval_reason"), dict):
                    normalized["retrieval_reason"]["backend"] = "mem0_vector"
                out.append(normalized)
        if out:
            source_counts["source_vector"] = len(out)
        if not out and allow_get_all_fallback:
            out, rejected = self._fallback_search_via_get_all(
                query,
                top_k=top_k,
                allowed_sources=allowed_sources,
                max_summary_chars=max_summary_chars,
                reject_blob_like=reject_blob_like,
            )
            source_counts["source_get_all"] = len(out)
            source_counts["rejected_blob_like"] += int(rejected)
        if not out and allow_history_fallback:
            out, rejected = self._fallback_search_via_history_db(
                query,
                top_k=top_k,
                max_summary_chars=max_summary_chars,
                reject_blob_like=reject_blob_like,
            )
            source_counts["source_history"] = len(out)
            source_counts["rejected_blob_like"] += int(rejected)
        out.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        sliced = out[: max(1, top_k)]
        return (sliced, source_counts) if return_stats else sliced

    def update(self, memory_id: str, text: str, *, metadata: dict[str, Any] | None = None) -> bool:
        if not self.enabled or not self.client or not memory_id.strip() or not text.strip():
            return False
        try:
            if self.mode == "hosted":
                self.client.update(memory_id, text=text, metadata=metadata)
            else:
                self.client.update(memory_id, text)
            return True
        except TypeError:
            try:
                self.client.update(memory_id, data=text)
                return True
            except Exception:  # crash-barrier: mem0 SDK
                return False
        except Exception as exc:  # crash-barrier: mem0 SDK
            if self._activate_local_fallback(reason=f"update failed: {exc}") and self.client:
                try:
                    self.client.update(memory_id, text)
                    return True
                except Exception:  # crash-barrier: mem0 SDK
                    return False
            return False

    def delete(self, memory_id: str) -> bool:
        if not self.enabled or not self.client or not memory_id.strip():
            return False
        try:
            self.client.delete(memory_id)
            return True
        except Exception as exc:  # crash-barrier: mem0 SDK
            if self._activate_local_fallback(reason=f"delete failed: {exc}") and self.client:
                try:
                    self.client.delete(memory_id)
                    return True
                except Exception:  # crash-barrier: mem0 SDK
                    return False
            return False


class _Mem0RuntimeInfo:
    """Compatibility surface for places that introspect backend name."""

    active_backend = "mem0"

    @staticmethod
    def rebuild_event_embeddings(*args: Any, **kwargs: Any) -> None:
        return None

    @staticmethod
    def ensure_event_embeddings(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}
