"""Memory system for persistent agent memory."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session

try:
    from mem0 import Memory as Mem0Memory
except Exception:  # pragma: no cover - optional dependency
    Mem0Memory = None

try:
    from mem0 import MemoryClient as Mem0MemoryClient
except Exception:  # pragma: no cover - optional dependency
    Mem0MemoryClient = None


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
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


_SAVE_EVENTS_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_events",
            "description": "Extract structured memory events and profile updates from conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "events": {
                        "type": "array",
                        "description": "Notable events extracted from conversation.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "timestamp": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "description": "preference|fact|task|decision|constraint|relationship",
                                },
                                "summary": {"type": "string"},
                                "entities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "salience": {"type": "number"},
                                "confidence": {"type": "number"},
                                "ttl_days": {"type": "integer"},
                            },
                            "required": ["type", "summary"],
                        },
                    },
                    "profile_updates": {
                        "type": "object",
                        "properties": {
                            "preferences": {"type": "array", "items": {"type": "string"}},
                            "stable_facts": {"type": "array", "items": {"type": "string"}},
                            "active_projects": {"type": "array", "items": {"type": "string"}},
                            "relationships": {"type": "array", "items": {"type": "string"}},
                            "constraints": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "required": ["events", "profile_updates"],
            },
        },
    }
]


class MemoryPersistence:
    """Low-level persistence for memory files and JSON payloads."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.events_file = self.memory_dir / "events.jsonl"
        self.profile_file = self.memory_dir / "profile.json"
        self.metrics_file = self.memory_dir / "metrics.json"

    @staticmethod
    def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, (dict, list)):
                return data
        except Exception:
            return None
        return None

    @staticmethod
    def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
        return out

    @staticmethod
    def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def append_text(path: Path, text: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)

    @staticmethod
    def read_text(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def write_text(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")


class MemoryExtractor:
    """LLM + heuristic extraction component extracted from MemoryStore."""

    def __init__(
        self,
        *,
        to_str_list: Any,
        coerce_event: Any,
        utc_now_iso: Any,
    ):
        self.to_str_list = to_str_list
        self.coerce_event = coerce_event
        self.utc_now_iso = utc_now_iso

    @staticmethod
    def default_profile_updates() -> dict[str, list[str]]:
        return {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }

    @staticmethod
    def parse_tool_args(args: Any) -> dict[str, Any] | None:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        return args if isinstance(args, dict) else None

    @staticmethod
    def count_user_corrections(messages: list[dict[str, Any]]) -> int:
        correction_patterns = (
            "that's wrong",
            "that is wrong",
            "you are wrong",
            "incorrect",
            "actually",
            "correction",
            "update that",
            "not true",
            "let me correct",
            "i meant",
        )
        count = 0
        for message in messages:
            if str(message.get("role", "")).lower() != "user":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            lowered = content.lower()
            if any(pattern in lowered for pattern in correction_patterns):
                count += 1
        return count

    @staticmethod
    def _clean_phrase(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value.strip().strip(".,;:!?\"'()[]{}"))
        cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def extract_explicit_preference_corrections(self, content: str) -> list[tuple[str, str]]:
        text = str(content or "").strip()
        if not text:
            return []

        matches: list[tuple[str, str]] = []
        patterns = (
            (
                r"(?:correction\s*[:,-]?\s*)?(?:i\s+(?:now\s+)?)?(?:prefer|want|use)\s+(.+?)\s*(?:,|;|\s+but)?\s*not\s+(.+?)(?:[.!?]|$)",
                "new_old",
            ),
            (
                r"(?:correction\s*[:,-]?\s*)?(?:not\s+)(.+?)\s*(?:,|;|\s+but)\s*(?:i\s+(?:now\s+)?)?(?:prefer|want|use)\s+(.+?)(?:[.!?]|$)",
                "old_new",
            ),
        )

        for pattern, order in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                if order == "new_old":
                    new_value = self._clean_phrase(match.group(1))
                    old_value = self._clean_phrase(match.group(2))
                else:
                    old_value = self._clean_phrase(match.group(1))
                    new_value = self._clean_phrase(match.group(2))
                if not new_value or not old_value:
                    continue
                if self._clean_phrase(new_value).lower() == self._clean_phrase(old_value).lower():
                    continue
                matches.append((new_value, old_value))

        dedup: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for new_value, old_value in matches:
            key = (new_value.lower(), old_value.lower())
            if key in seen:
                continue
            seen.add(key)
            dedup.append((new_value, old_value))
        return dedup

    def extract_explicit_fact_corrections(self, content: str) -> list[tuple[str, str]]:
        text = str(content or "").strip()
        if not text:
            return []

        matches: list[tuple[str, str]] = []
        patterns = (
            r"(?:correction\s*[:,-]?\s*)?(?:actually\s+)?([a-zA-Z0-9_\- ]{2,80}?)\s+is\s+(.+?)\s*(?:,|;|\s+but)?\s*not\s+(.+?)(?:[.!?]|$)",
            r"(?:correction\s*[:,-]?\s*)?(?:actually\s+)?([a-zA-Z0-9_\- ]{2,80}?)\s+is\s+not\s+(.+?)\s*(?:,|;|\s+but)\s*(?:it(?:'s| is)|is)\s+(.+?)(?:[.!?]|$)",
        )

        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                subject = self._clean_phrase(match.group(1))
                if "prefer" in subject.lower() or "want" in subject.lower() or "use" in subject.lower():
                    continue

                if "is not" in pattern:
                    old_value = self._clean_phrase(match.group(2))
                    new_value = self._clean_phrase(match.group(3))
                else:
                    new_value = self._clean_phrase(match.group(2))
                    old_value = self._clean_phrase(match.group(3))

                if not subject or not new_value or not old_value:
                    continue

                new_fact = f"{subject} is {new_value}"
                old_fact = f"{subject} is {old_value}"
                if self._clean_phrase(new_fact).lower() == self._clean_phrase(old_fact).lower():
                    continue
                matches.append((new_fact, old_fact))

        dedup: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for new_value, old_value in matches:
            key = (new_value.lower(), old_value.lower())
            if key in seen:
                continue
            seen.add(key)
            dedup.append((new_value, old_value))
        return dedup

    def heuristic_extract_events(
        self,
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        updates = self.default_profile_updates()
        events: list[dict[str, Any]] = []

        type_hints = [
            ("preference", ("prefer", "i like", "i dislike", "my preference")),
            ("constraint", ("must", "cannot", "can't", "do not", "never")),
            ("decision", ("decided", "we will", "let's", "plan is")),
            ("task", ("todo", "next step", "please", "need to")),
            ("relationship", ("is my", "works with", "project lead", "manager")),
        ]

        for offset, message in enumerate(old_messages):
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            if message.get("role") != "user":
                continue
            text = content.strip()
            lowered = text.lower()

            event_type = "fact"
            for candidate, needles in type_hints:
                if any(needle in lowered for needle in needles):
                    event_type = candidate
                    break

            summary = text if len(text) <= 220 else text[:217] + "..."
            source_span = [source_start + offset, source_start + offset]
            event = self.coerce_event(
                {
                    "timestamp": message.get("timestamp") or self.utc_now_iso(),
                    "type": event_type,
                    "summary": summary,
                    "entities": [],
                    "salience": 0.55,
                    "confidence": 0.6,
                },
                source_span=source_span,
            )
            if event:
                events.append(event)

            if event_type == "preference":
                updates["preferences"].append(summary)
            elif event_type == "constraint":
                updates["constraints"].append(summary)
            elif event_type == "relationship":
                updates["relationships"].append(summary)
            else:
                updates["stable_facts"].append(summary)

        for key in updates:
            updates[key] = list(dict.fromkeys(updates[key]))
        return events[:20], updates

    async def extract_structured_memory(
        self,
        provider: LLMProvider,
        model: str,
        current_profile: dict[str, Any],
        lines: list[str],
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        prompt = (
            "Extract structured memory from this conversation and call save_events. "
            "Only include actionable long-term information.\n\n"
            "## Current Profile\n"
            f"{json.dumps(current_profile, ensure_ascii=False)}\n\n"
            "## Conversation\n"
            f"{chr(10).join(lines)}"
        )
        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a structured memory extractor. Call save_events with events and profile_updates.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_EVENTS_TOOL,
                model=model,
            )
            if response.has_tool_calls:
                args = self.parse_tool_args(response.tool_calls[0].arguments)
                if args:
                    raw_events = args.get("events") if isinstance(args.get("events"), list) else []
                    raw_updates = args.get("profile_updates") if isinstance(args.get("profile_updates"), dict) else {}
                    updates = self.default_profile_updates()
                    for key in updates:
                        updates[key] = self.to_str_list(raw_updates.get(key))

                    events: list[dict[str, Any]] = []
                    for _, item in enumerate(raw_events):
                        if not isinstance(item, dict):
                            continue
                        source_span = item.get("source_span")
                        if (
                            not isinstance(source_span, list)
                            or len(source_span) != 2
                            or not all(isinstance(x, int) for x in source_span)
                        ):
                            source_span = [source_start, source_start + max(len(old_messages) - 1, 0)]
                        event = self.coerce_event(item, source_span=source_span)
                        if event:
                            events.append(event)
                        if len(events) >= 40:
                            break
                    return events, updates
        except Exception:
            logger.exception("Structured event extraction failed, falling back to heuristic extraction")

        return self.heuristic_extract_events(old_messages, source_start=source_start)


class _Mem0Adapter:
    """Thin compatibility wrapper around mem0 OSS/hosted clients."""

    def __init__(self, *, workspace: Path):
        self.workspace = workspace
        self.user_id = os.getenv("NANOBOT_MEM0_USER_ID", "nanobot")
        self.enabled = False
        self.client: Any | None = None
        self.mode = "disabled"
        self.error: str | None = None
        self._local_fallback_attempted = False
        self._local_mem0_dir: Path | None = None
        self._fallback_enabled = True
        self._fallback_candidates: list[tuple[str, dict[str, Any], int]] = [
            ("fastembed", {"model": "BAAI/bge-small-en-v1.5"}, 384),
            ("huggingface", {"model": "sentence-transformers/all-MiniLM-L6-v2"}, 384),
        ]
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
                config = item.get("config") if isinstance(item.get("config"), dict) else {}
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
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
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
            except Exception:
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
            except Exception:
                continue

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
        except Exception:
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
            except Exception as exc:
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
            except Exception:
                payload = None
        self._load_fallback_config(payload)

        try:
            if payload is not None:
                mem0_payload = dict(payload)
                mem0_payload.pop("fallback", None)
                self.client = Mem0Memory.from_config(mem0_payload)
            else:
                # Force local writable persistence instead of ~/.mem0/*
                self.client = Mem0Memory.from_config(
                    {
                        "history_db_path": str(local_mem0_dir / "history.db"),
                        "vector_store": {
                            "provider": "qdrant",
                            "config": {
                                "collection_name": "nanobot_mem0",
                                "path": str(local_mem0_dir / "qdrant"),
                            },
                        },
                    }
                )
            self.enabled = True
            self.mode = "oss"
            return
        except Exception as exc:
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
                        "embedder": {"provider": provider, "config": embedder_cfg},
                        "vector_store": {
                            "provider": "qdrant",
                            "config": {
                                "collection_name": f"nanobot_mem0_local_{provider}",
                                "path": str(local_mem0_dir / "qdrant"),
                                "embedding_model_dims": dims,
                            },
                        },
                        "history_db_path": str(local_mem0_dir / "history.db"),
                    }
                )
                self.enabled = True
                self.mode = f"oss-local-fallback-{provider}"
                self.error = None
                logger.warning("mem0 switched to local fallback embedder ({}): {}", provider, reason)
                return True
            except Exception as exc:
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

    def add_text(self, text: str, *, metadata: dict[str, Any] | None = None) -> bool:
        if not self.enabled or not self.client or not text.strip():
            return False
        messages = [{"role": "user", "content": text.strip()}]
        kwargs: dict[str, Any] = {"user_id": self.user_id}
        if metadata:
            kwargs["metadata"] = metadata
        try:
            self.client.add(messages, infer=False, **kwargs)
            return True
        except TypeError:
            try:
                self.client.add(messages, **kwargs)
                return True
            except Exception:
                return False
        except Exception as exc:
            if self._activate_local_fallback(reason=f"add_text failed: {exc}") and self.client:
                try:
                    self.client.add(messages, infer=False, **kwargs)
                    return True
                except TypeError:
                    try:
                        self.client.add(messages, **kwargs)
                        return True
                    except Exception:
                        return False
                except Exception:
                    return False
            return False

    def search(self, query: str, *, top_k: int = 6) -> list[dict[str, Any]]:
        if not self.enabled or not self.client or not query.strip():
            return []
        kwargs: dict[str, Any] = {"user_id": self.user_id, "limit": max(1, top_k)}
        try:
            raw = self.client.search(query=query, **kwargs)
        except TypeError:
            try:
                raw = self.client.search(query, **kwargs)
            except Exception:
                return []
        except Exception as exc:
            if self._activate_local_fallback(reason=f"search failed: {exc}") and self.client:
                try:
                    raw = self.client.search(query=query, **kwargs)
                except TypeError:
                    try:
                        raw = self.client.search(query, **kwargs)
                    except Exception:
                        return []
                except Exception:
                    return []
            else:
                return []

        out: list[dict[str, Any]] = []
        for item in self._rows(raw):
            summary = str(item.get("memory") or item.get("text") or item.get("summary") or "").strip()
            if not summary:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            timestamp = (
                item.get("updated_at")
                or item.get("created_at")
                or metadata.get("timestamp")
                or ""
            )
            event_type = str(metadata.get("event_type", "fact"))
            try:
                score = float(item.get("score", 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            canonical_id = str(item.get("id") or hashlib.sha1(summary.encode("utf-8")).hexdigest())
            out.append(
                {
                    "id": canonical_id,
                    "timestamp": str(timestamp),
                    "type": event_type,
                    "summary": summary,
                    "entities": metadata.get("entities", []),
                    "score": score,
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
            )
        out.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return out[: max(1, top_k)]

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
            except Exception:
                return False
        except Exception as exc:
            if self._activate_local_fallback(reason=f"update failed: {exc}") and self.client:
                try:
                    self.client.update(memory_id, text)
                    return True
                except Exception:
                    return False
            return False

    def delete(self, memory_id: str) -> bool:
        if not self.enabled or not self.client or not memory_id.strip():
            return False
        try:
            self.client.delete(memory_id)
            return True
        except Exception as exc:
            if self._activate_local_fallback(reason=f"delete failed: {exc}") and self.client:
                try:
                    self.client.delete(memory_id)
                    return True
                except Exception:
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


class MemoryStore:
    """mem0-first memory store with structured profile/events maintenance."""

    PROFILE_KEYS = ("preferences", "stable_facts", "active_projects", "relationships", "constraints")
    EVENT_TYPES = {"preference", "fact", "task", "decision", "constraint", "relationship"}
    PROFILE_STATUS_ACTIVE = "active"
    PROFILE_STATUS_CONFLICTED = "conflicted"
    PROFILE_STATUS_STALE = "stale"
    CONFLICT_STATUS_OPEN = "open"
    CONFLICT_STATUS_NEEDS_USER = "needs_user"
    CONFLICT_STATUS_RESOLVED = "resolved"

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.persistence = MemoryPersistence(workspace)
        self.memory_dir = self.persistence.memory_dir
        self.memory_file = self.persistence.memory_file
        self.history_file = self.persistence.history_file
        self.events_file = self.persistence.events_file
        self.profile_file = self.persistence.profile_file
        self.metrics_file = self.persistence.metrics_file
        self.retriever = _Mem0RuntimeInfo()
        self.extractor = MemoryExtractor(
            to_str_list=self._to_str_list,
            coerce_event=self._coerce_event,
            utc_now_iso=self._utc_now_iso,
        )
        self.mem0 = _Mem0Adapter(workspace=workspace)

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _norm_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        return {t for t in re.findall(r"[a-zA-Z0-9_\-]+", value.lower()) if len(t) > 1}

    @staticmethod
    def _to_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    @staticmethod
    def _to_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _load_metrics(self) -> dict[str, Any]:
        data = self.persistence.read_json(self.metrics_file)
        if isinstance(data, dict):
            return data
        if self.metrics_file.exists():
            logger.warning("Failed to parse memory metrics, resetting")
        return {
            "consolidations": 0,
            "events_extracted": 0,
            "event_dedup_merges": 0,
            "retrieval_queries": 0,
            "retrieval_hits": 0,
            "index_updates": 0,
            "conflicts_detected": 0,
            "messages_processed": 0,
            "user_messages_processed": 0,
            "user_corrections": 0,
            "profile_updates_applied": 0,
            "memory_context_calls": 0,
            "memory_context_tokens_total": 0,
            "memory_context_tokens_max": 0,
            "last_updated": self._utc_now_iso(),
        }

    def _record_metric(self, key: str, delta: int = 1) -> None:
        self._record_metrics({key: delta})

    def _record_metrics(self, deltas: dict[str, int]) -> None:
        metrics = self._load_metrics()
        for key, delta in deltas.items():
            metrics[key] = int(metrics.get(key, 0)) + int(delta)
        metrics["last_updated"] = self._utc_now_iso()
        self.persistence.write_json(self.metrics_file, metrics)

    def get_metrics(self) -> dict[str, Any]:
        return self._load_metrics()

    def get_observability_report(self) -> dict[str, Any]:
        metrics = self.get_metrics()
        retrieval_queries = max(int(metrics.get("retrieval_queries", 0)), 0)
        retrieval_hits = max(int(metrics.get("retrieval_hits", 0)), 0)
        messages_processed = max(int(metrics.get("messages_processed", 0)), 0)
        user_messages_processed = max(int(metrics.get("user_messages_processed", 0)), 0)
        user_corrections = max(int(metrics.get("user_corrections", 0)), 0)
        conflicts_detected = max(int(metrics.get("conflicts_detected", 0)), 0)
        memory_context_calls = max(int(metrics.get("memory_context_calls", 0)), 0)
        memory_context_tokens_total = max(int(metrics.get("memory_context_tokens_total", 0)), 0)
        memory_context_tokens_max = max(int(metrics.get("memory_context_tokens_max", 0)), 0)

        retrieval_hit_rate = (retrieval_hits / retrieval_queries) if retrieval_queries else 0.0
        contradiction_rate_per_100 = (conflicts_detected * 100.0 / messages_processed) if messages_processed else 0.0
        user_correction_rate_per_100 = (user_corrections * 100.0 / user_messages_processed) if user_messages_processed else 0.0
        avg_memory_context_tokens = (memory_context_tokens_total / memory_context_calls) if memory_context_calls else 0.0

        return {
            "metrics": metrics,
            "kpis": {
                "retrieval_hit_rate": round(retrieval_hit_rate, 4),
                "contradiction_rate_per_100_messages": round(contradiction_rate_per_100, 4),
                "user_correction_rate_per_100_user_messages": round(user_correction_rate_per_100, 4),
                "avg_memory_context_tokens": round(avg_memory_context_tokens, 2),
                "max_memory_context_tokens": memory_context_tokens_max,
            },
            "backend": {
                "mem0_enabled": self.mem0.enabled,
                "mem0_mode": self.mem0.mode,
            },
        }

    def evaluate_retrieval_cases(
        self,
        cases: list[dict[str, Any]],
        *,
        default_top_k: int = 6,
    ) -> dict[str, Any]:
        """Evaluate retrieval quality using labeled cases.

        Case format (each dict):
        - query: str (required)
        - expected_ids: list[str] (optional)
        - expected_any: list[str] substrings expected in retrieved summaries (optional)
        - top_k: int (optional)
        """
        valid_cases = [c for c in cases if isinstance(c, dict) and isinstance(c.get("query"), str) and c.get("query", "").strip()]
        if not valid_cases:
            return {
                "cases": 0,
                "evaluated": [],
                "summary": {
                    "recall_at_k": 0.0,
                    "precision_at_k": 0.0,
                },
            }

        total_expected = 0
        total_found = 0
        total_relevant_retrieved = 0
        total_retrieved_slots = 0
        evaluated: list[dict[str, Any]] = []

        for case in valid_cases:
            query = str(case.get("query", "")).strip()
            top_k = int(case.get("top_k", default_top_k) or default_top_k)
            top_k = max(1, min(top_k, 30))

            expected_ids = [str(x) for x in case.get("expected_ids", []) if isinstance(x, str) and x.strip()]
            expected_any = [str(x).lower() for x in case.get("expected_any", []) if isinstance(x, str) and x.strip()]

            retrieved = self.retrieve(
                query,
                top_k=top_k,
            )

            hits = 0
            relevant_retrieved = 0
            matched_expected_tokens: set[str] = set()

            for item in retrieved:
                summary = str(item.get("summary", "")).lower()
                event_id = str(item.get("id", ""))
                is_relevant = False

                for expected_id in expected_ids:
                    if expected_id == event_id:
                        matched_expected_tokens.add(f"id:{expected_id}")
                        is_relevant = True

                for expected_text in expected_any:
                    if expected_text in summary:
                        matched_expected_tokens.add(f"txt:{expected_text}")
                        is_relevant = True

                if is_relevant:
                    relevant_retrieved += 1

            expected_count = len(expected_ids) + len(expected_any)
            if expected_count > 0:
                hits = len(matched_expected_tokens)
                total_expected += expected_count
                total_found += hits

            total_relevant_retrieved += relevant_retrieved
            total_retrieved_slots += top_k

            case_recall = (hits / expected_count) if expected_count else 0.0
            case_precision = (relevant_retrieved / top_k) if top_k > 0 else 0.0
            evaluated.append(
                {
                    "query": query,
                    "top_k": top_k,
                    "expected": expected_count,
                    "hits": hits,
                    "retrieved": len(retrieved),
                    "case_recall_at_k": round(case_recall, 4),
                    "case_precision_at_k": round(case_precision, 4),
                }
            )

        overall_recall = (total_found / total_expected) if total_expected else 0.0
        overall_precision = (total_relevant_retrieved / total_retrieved_slots) if total_retrieved_slots else 0.0

        return {
            "cases": len(valid_cases),
            "evaluated": evaluated,
            "summary": {
                "recall_at_k": round(overall_recall, 4),
                "precision_at_k": round(overall_precision, 4),
            },
        }

    def save_evaluation_report(
        self,
        evaluation: dict[str, Any],
        observability: dict[str, Any],
        *,
        output_file: str | None = None,
    ) -> Path:
        """Persist evaluation + observability report to disk and return the file path."""
        reports_dir = ensure_dir(self.memory_dir / "reports")
        if output_file:
            path = Path(output_file).expanduser().resolve()
            ensure_dir(path.parent)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = reports_dir / f"memory_eval_{ts}.json"

        payload = {
            "generated_at": self._utc_now_iso(),
            "evaluation": evaluation,
            "observability": observability,
        }
        self.persistence.write_json(path, payload)
        return path

    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        out = self.persistence.read_jsonl(self.events_file)
        if limit is not None and limit > 0:
            return out[-limit:]
        return out

    @staticmethod
    def _merge_source_span(base: list[int] | Any, incoming: list[int] | Any) -> list[int]:
        base_span = base if isinstance(base, list) and len(base) == 2 and all(isinstance(x, int) for x in base) else [0, 0]
        incoming_span = (
            incoming if isinstance(incoming, list) and len(incoming) == 2 and all(isinstance(x, int) for x in incoming) else base_span
        )
        return [min(base_span[0], incoming_span[0]), max(base_span[1], incoming_span[1])]

    def _ensure_event_provenance(self, event: dict[str, Any]) -> dict[str, Any]:
        event_copy = dict(event)
        event_id = str(event_copy.get("id", "")).strip()
        if not event_id:
            return event_copy

        event_copy.setdefault("canonical_id", event_id)
        aliases = event_copy.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        summary = str(event_copy.get("summary", "")).strip()
        if summary and summary not in aliases:
            aliases.append(summary)
        event_copy["aliases"] = aliases

        evidence = event_copy.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
        if not evidence:
            evidence.append(
                {
                    "event_id": event_id,
                    "timestamp": str(event_copy.get("timestamp", "")),
                    "summary": summary,
                    "source_span": event_copy.get("source_span"),
                    "confidence": self._safe_float(event_copy.get("confidence"), 0.7),
                    "salience": self._safe_float(event_copy.get("salience"), 0.6),
                }
            )
        event_copy["evidence"] = evidence
        event_copy["merged_event_count"] = max(int(event_copy.get("merged_event_count", 1)), 1)
        return event_copy

    def _event_similarity(self, left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
        def _event_text(event: dict[str, Any]) -> str:
            summary = str(event.get("summary", ""))
            entities = " ".join(self._to_str_list(event.get("entities")))
            event_type = str(event.get("type", "fact"))
            return f"{event_type}. {summary}. {entities}".strip()

        left_text = _event_text(left)
        right_text = _event_text(right)

        left_tokens = self._tokenize(left_text)
        right_tokens = self._tokenize(right_text)
        overlap = left_tokens & right_tokens
        union = left_tokens | right_tokens
        lexical = (len(overlap) / len(union)) if union else 0.0
        semantic = lexical
        return lexical, semantic

    def _find_semantic_duplicate(
        self,
        candidate: dict[str, Any],
        existing_events: list[dict[str, Any]],
    ) -> tuple[int | None, float]:
        best_idx: int | None = None
        best_score = 0.0
        candidate_type = str(candidate.get("type", ""))

        for idx, existing in enumerate(existing_events):
            if str(existing.get("type", "")) != candidate_type:
                continue
            lexical, semantic = self._event_similarity(candidate, existing)
            candidate_entities = {self._norm_text(x) for x in self._to_str_list(candidate.get("entities"))}
            existing_entities = {self._norm_text(x) for x in self._to_str_list(existing.get("entities"))}
            entity_overlap = 0.0
            if candidate_entities and existing_entities:
                entity_overlap = len(candidate_entities & existing_entities) / max(len(candidate_entities | existing_entities), 1)

            score = 0.4 * semantic + 0.45 * lexical + 0.15 * entity_overlap
            is_duplicate = (
                lexical >= 0.84
                or semantic >= 0.94
                or (lexical >= 0.6 and semantic >= 0.86)
                or (entity_overlap >= 0.33 and (lexical >= 0.42 or semantic >= 0.52))
            )
            if not is_duplicate:
                continue
            if score > best_score:
                best_score = score
                best_idx = idx

        return best_idx, best_score

    def _merge_events(
        self,
        base: dict[str, Any],
        incoming: dict[str, Any],
        *,
        similarity: float,
    ) -> dict[str, Any]:
        canonical = self._ensure_event_provenance(base)
        candidate = self._ensure_event_provenance(incoming)

        entities = list(dict.fromkeys(self._to_str_list(canonical.get("entities")) + self._to_str_list(candidate.get("entities"))))
        aliases = list(dict.fromkeys(self._to_str_list(canonical.get("aliases")) + self._to_str_list(candidate.get("aliases"))))
        evidence = canonical.get("evidence") if isinstance(canonical.get("evidence"), list) else []
        evidence.extend(candidate.get("evidence") if isinstance(candidate.get("evidence"), list) else [])
        if len(evidence) > 20:
            evidence = evidence[-20:]

        merged_count = max(int(canonical.get("merged_event_count", 1)), 1) + 1
        c_conf = self._safe_float(canonical.get("confidence"), 0.7)
        i_conf = self._safe_float(candidate.get("confidence"), 0.7)
        c_sal = self._safe_float(canonical.get("salience"), 0.6)
        i_sal = self._safe_float(candidate.get("salience"), 0.6)

        merged = dict(canonical)
        merged["summary"] = str(canonical.get("summary") or candidate.get("summary") or "")
        merged["entities"] = entities
        merged["aliases"] = aliases
        merged["evidence"] = evidence
        merged["source_span"] = self._merge_source_span(canonical.get("source_span"), candidate.get("source_span"))
        merged["confidence"] = min(max((c_conf + i_conf) / 2.0 + 0.03, 0.0), 1.0)
        merged["salience"] = min(max(max(c_sal, i_sal), 0.0), 1.0)
        merged["merged_event_count"] = merged_count
        merged["last_merged_at"] = self._utc_now_iso()
        merged["last_dedup_score"] = round(similarity, 4)
        merged["canonical_id"] = str(canonical.get("canonical_id") or canonical.get("id", ""))

        canonical_ts = self._to_datetime(str(canonical.get("timestamp", "")))
        candidate_ts = self._to_datetime(str(candidate.get("timestamp", "")))
        if canonical_ts and candidate_ts and candidate_ts > canonical_ts:
            merged["timestamp"] = str(candidate.get("timestamp", merged.get("timestamp", "")))
        return merged

    def append_events(self, events: list[dict[str, Any]]) -> int:
        if not events:
            return 0
        existing_events = [self._ensure_event_provenance(event) for event in self.read_events()]
        existing_ids = {e.get("id") for e in existing_events if e.get("id")}
        written = 0
        merged = 0
        appended_events: list[dict[str, Any]] = []

        for raw in events:
            event_id = raw.get("id")
            if not event_id:
                continue
            candidate = self._ensure_event_provenance(raw)

            if event_id in existing_ids:
                for idx, existing in enumerate(existing_events):
                    if existing.get("id") == event_id:
                        existing_events[idx] = self._merge_events(existing, candidate, similarity=1.0)
                        merged += 1
                        break
                continue

            dup_idx, dup_score = self._find_semantic_duplicate(candidate, existing_events)
            if dup_idx is not None:
                existing_events[dup_idx] = self._merge_events(existing_events[dup_idx], candidate, similarity=dup_score)
                merged += 1
                continue

            existing_ids.add(event_id)
            existing_events.append(candidate)
            appended_events.append(candidate)
            written += 1

        if written <= 0 and merged <= 0:
            return 0

        self.persistence.write_jsonl(self.events_file, existing_events)
        if merged > 0:
            self._record_metric("event_dedup_merges", merged)

        if written > 0 and self.mem0.enabled:
            for event in appended_events:
                summary = str(event.get("summary", "")).strip()
                if not summary:
                    continue
                metadata = {
                    "event_type": str(event.get("type", "fact")),
                    "timestamp": str(event.get("timestamp", "")),
                    "entities": self._to_str_list(event.get("entities")),
                    "source_span": event.get("source_span"),
                    "channel": str(event.get("channel", "")),
                    "chat_id": str(event.get("chat_id", "")),
                }
                self.mem0.add_text(summary, metadata=metadata)
        return written

    def read_profile(self) -> dict[str, Any]:
        data = self.persistence.read_json(self.profile_file)
        if isinstance(data, dict):
            for key in self.PROFILE_KEYS:
                data.setdefault(key, [])
                if not isinstance(data[key], list):
                    data[key] = []
            data.setdefault("conflicts", [])
            data.setdefault("last_verified_at", None)
            data.setdefault("meta", {})
            for key in self.PROFILE_KEYS:
                section_meta = data["meta"].get(key)
                if not isinstance(section_meta, dict):
                    section_meta = {}
                    data["meta"][key] = section_meta
                for item in data[key]:
                    if not isinstance(item, str) or not item.strip():
                        continue
                    norm = self._norm_text(item)
                    entry = section_meta.get(norm)
                    if not isinstance(entry, dict):
                        section_meta[norm] = {
                            "text": item,
                            "confidence": 0.65,
                            "evidence_count": 1,
                            "status": self.PROFILE_STATUS_ACTIVE,
                            "last_seen_at": data.get("updated_at") or self._utc_now_iso(),
                        }
            return data
        if self.profile_file.exists():
            logger.warning("Failed to parse memory profile, resetting")
        return {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "last_verified_at": None,
            "meta": {key: {} for key in self.PROFILE_KEYS},
            "updated_at": self._utc_now_iso(),
        }

    def _meta_section(self, profile: dict[str, Any], key: str) -> dict[str, Any]:
        profile.setdefault("meta", {})
        section = profile["meta"].get(key)
        if not isinstance(section, dict):
            section = {}
            profile["meta"][key] = section
        return section

    def _meta_entry(self, profile: dict[str, Any], key: str, text: str) -> dict[str, Any]:
        norm = self._norm_text(text)
        section = self._meta_section(profile, key)
        entry = section.get(norm)
        if not isinstance(entry, dict):
            entry = {
                "text": text,
                "confidence": 0.65,
                "evidence_count": 1,
                "status": self.PROFILE_STATUS_ACTIVE,
                "last_seen_at": self._utc_now_iso(),
            }
            section[norm] = entry
        return entry

    def _touch_meta_entry(
        self,
        entry: dict[str, Any],
        *,
        confidence_delta: float,
        min_confidence: float = 0.05,
        max_confidence: float = 0.99,
        status: str | None = None,
    ) -> None:
        current_conf = self._safe_float(entry.get("confidence"), 0.65)
        entry["confidence"] = min(max(current_conf + confidence_delta, min_confidence), max_confidence)
        evidence = int(entry.get("evidence_count", 0)) + 1
        entry["evidence_count"] = max(evidence, 1)
        entry["last_seen_at"] = self._utc_now_iso()
        if status:
            entry["status"] = status

    def _validate_profile_field(self, field: str) -> str:
        key = str(field or "").strip()
        if key not in self.PROFILE_KEYS:
            raise ValueError(f"Invalid profile field '{field}'. Expected one of: {', '.join(self.PROFILE_KEYS)}")
        return key

    def set_item_pin(self, field: str, text: str, *, pinned: bool) -> bool:
        key = self._validate_profile_field(field)
        value = str(text or "").strip()
        if not value:
            return False

        profile = self.read_profile()
        values = self._to_str_list(profile.get(key))
        normalized = self._norm_text(value)
        existing_map = {self._norm_text(v): v for v in values}
        if normalized not in existing_map:
            values.append(value)
            profile[key] = values

        canonical = existing_map.get(normalized, value)
        entry = self._meta_entry(profile, key, canonical)
        entry["pinned"] = bool(pinned)
        entry["last_seen_at"] = self._utc_now_iso()
        if entry.get("status") == self.PROFILE_STATUS_STALE and pinned:
            entry["status"] = self.PROFILE_STATUS_ACTIVE
        self.write_profile(profile)
        return True

    def mark_item_outdated(self, field: str, text: str) -> bool:
        key = self._validate_profile_field(field)
        value = str(text or "").strip()
        if not value:
            return False

        profile = self.read_profile()
        values = self._to_str_list(profile.get(key))
        normalized = self._norm_text(value)
        existing = None
        for item in values:
            if self._norm_text(item) == normalized:
                existing = item
                break
        if existing is None:
            return False

        entry = self._meta_entry(profile, key, existing)
        entry["status"] = self.PROFILE_STATUS_STALE
        entry["last_seen_at"] = self._utc_now_iso()
        self.write_profile(profile)
        return True

    def list_conflicts(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return []

        out: list[dict[str, Any]] = []
        for idx, item in enumerate(conflicts):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            if not include_closed and status not in {self.CONFLICT_STATUS_OPEN, self.CONFLICT_STATUS_NEEDS_USER}:
                continue
            row = dict(item)
            row["index"] = idx
            out.append(row)
        return out

    @staticmethod
    def _parse_conflict_user_action(text: str) -> str | None:
        content = str(text or "").strip().lower()
        if not content:
            return None
        keep_old_markers = {"keep 1", "1", "old", "keep old", "keep_old"}
        keep_new_markers = {"keep 2", "2", "new", "keep new", "keep_new"}
        dismiss_markers = {"neither", "dismiss", "none", "skip"}
        merge_markers = {"merge", "combine"}
        if content in keep_old_markers:
            return "keep_old"
        if content in keep_new_markers:
            return "keep_new"
        if content in dismiss_markers:
            return "dismiss"
        if content in merge_markers:
            return "merge"
        return None

    def _auto_resolution_action(self, conflict: dict[str, Any]) -> str | None:
        source = str(conflict.get("source", "")).strip().lower()
        if source == "live_correction":
            return "keep_new"

        old_conf = self._safe_float(conflict.get("old_confidence"), 0.0)
        new_conf = self._safe_float(conflict.get("new_confidence"), 0.0)
        gap = abs(old_conf - new_conf)
        if gap < 0.25:
            return None
        return "keep_new" if new_conf > old_conf else "keep_old"

    def auto_resolve_conflicts(self, *, max_items: int = 10) -> dict[str, int]:
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return {"auto_resolved": 0, "needs_user": 0}

        auto_resolved = 0
        needs_user = 0
        touched = False
        for idx, conflict in enumerate(conflicts):
            if max_items <= 0:
                break
            if not isinstance(conflict, dict):
                continue
            status = str(conflict.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            if status not in {self.CONFLICT_STATUS_OPEN, self.CONFLICT_STATUS_NEEDS_USER}:
                continue
            max_items -= 1

            action = self._auto_resolution_action(conflict)
            if action is None:
                if status != self.CONFLICT_STATUS_NEEDS_USER:
                    conflict["status"] = self.CONFLICT_STATUS_NEEDS_USER
                    touched = True
                needs_user += 1
                continue

            details = self.resolve_conflict_details(idx, action)
            if details.get("ok"):
                auto_resolved += 1
                continue

            conflict["status"] = self.CONFLICT_STATUS_NEEDS_USER
            touched = True
            needs_user += 1

        if touched:
            self.write_profile(profile)
        return {"auto_resolved": auto_resolved, "needs_user": needs_user}

    def get_next_user_conflict(self) -> dict[str, Any] | None:
        conflicts = self.list_conflicts(include_closed=False)
        if not conflicts:
            return None

        asked = [c for c in conflicts if isinstance(c.get("asked_at"), str) and c.get("asked_at")]
        pool = asked or conflicts
        if not pool:
            return None
        pool.sort(key=lambda c: str(c.get("asked_at", "")))
        return pool[0]

    def ask_user_for_conflict(self) -> str | None:
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            return None

        chosen_idx: int | None = None
        chosen: dict[str, Any] | None = None
        for idx, item in enumerate(conflicts):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            if status != self.CONFLICT_STATUS_NEEDS_USER:
                continue
            chosen_idx = idx
            chosen = item
            break

        if chosen_idx is None or chosen is None:
            return None

        if not chosen.get("asked_at"):
            chosen["asked_at"] = self._utc_now_iso()
            self.write_profile(profile)

        old_value = str(chosen.get("old", "")).strip()
        new_value = str(chosen.get("new", "")).strip()
        return (
            "I found a memory conflict and need your choice:\n"
            f"1. {old_value}\n"
            f"2. {new_value}\n"
            "Reply with: `keep 1`, `keep 2`, `merge`, or `neither`."
        )

    def handle_user_conflict_reply(self, text: str) -> dict[str, Any]:
        action = self._parse_conflict_user_action(text)
        if action is None:
            return {"handled": False}

        conflict = self.get_next_user_conflict()
        if not conflict:
            return {"handled": False}

        idx = int(conflict.get("index", -1))
        if idx < 0:
            return {"handled": False}

        selected = "keep_new" if action == "merge" else action
        details = self.resolve_conflict_details(index=idx, action=selected)
        if not details.get("ok"):
            return {
                "handled": True,
                "ok": False,
                "message": "I couldn't resolve that conflict automatically. Please try `keep 1` or `keep 2`.",
            }

        return {
            "handled": True,
            "ok": True,
            "message": (
                f"Resolved conflict #{idx} with action `{selected}` "
                f"(mem0 op: {details.get('mem0_operation', 'none')})."
            ),
        }

    def resolve_conflict_details(self, index: int, action: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "index": index,
            "action": str(action or "").strip().lower(),
            "field": "",
            "old": "",
            "new": "",
            "old_memory_id": "",
            "new_memory_id": "",
            "mem0_operation": "none",
            "mem0_ok": False,
        }
        profile = self.read_profile()
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list) or index < 0 or index >= len(conflicts):
            return result

        conflict = conflicts[index]
        if not isinstance(conflict, dict) or str(conflict.get("status", "")).strip().lower() not in {
            self.CONFLICT_STATUS_OPEN,
            self.CONFLICT_STATUS_NEEDS_USER,
        }:
            return result

        field = str(conflict.get("field", ""))
        result["field"] = field
        try:
            key = self._validate_profile_field(field)
        except ValueError:
            return result

        old_value = str(conflict.get("old", "")).strip()
        new_value = str(conflict.get("new", "")).strip()
        result["old"] = old_value
        result["new"] = new_value
        values = self._to_str_list(profile.get(key))
        old_memory_id = str(conflict.get("old_memory_id", "")).strip() or self._find_mem0_id_for_text(old_value)
        new_memory_id = str(conflict.get("new_memory_id", "")).strip() or self._find_mem0_id_for_text(new_value)
        if old_memory_id:
            conflict["old_memory_id"] = old_memory_id
        if new_memory_id:
            conflict["new_memory_id"] = new_memory_id

        result["old_memory_id"] = old_memory_id
        result["new_memory_id"] = new_memory_id

        def _remove_value(values_in: list[str], target: str) -> list[str]:
            target_norm = self._norm_text(target)
            return [v for v in values_in if self._norm_text(v) != target_norm]

        selected = str(action or "").strip().lower()
        mem0_ok = False
        if selected == "keep_old":
            if new_memory_id:
                mem0_ok = self.mem0.delete(new_memory_id)
                result["mem0_operation"] = "delete_new"
            else:
                mem0_ok = True
                result["mem0_operation"] = "none"
            values = _remove_value(values, new_value)
            old_entry = self._meta_entry(profile, key, old_value)
            self._touch_meta_entry(old_entry, confidence_delta=0.08, status=self.PROFILE_STATUS_ACTIVE)
            new_entry = self._meta_entry(profile, key, new_value)
            new_entry["status"] = self.PROFILE_STATUS_STALE
        elif selected == "keep_new":
            if old_memory_id:
                mem0_ok = self.mem0.update(old_memory_id, new_value)
                result["mem0_operation"] = "update_old_to_new"
                if mem0_ok and new_memory_id and new_memory_id != old_memory_id:
                    self.mem0.delete(new_memory_id)
                    conflict["new_memory_id"] = old_memory_id
                    result["new_memory_id"] = old_memory_id
            else:
                mem0_ok = self.mem0.add_text(
                    new_value,
                    metadata={"event_type": "conflict_resolution", "field": key, "source": "resolve_conflict"},
                )
                result["mem0_operation"] = "add_new"
            values = _remove_value(values, old_value)
            new_entry = self._meta_entry(profile, key, new_value)
            self._touch_meta_entry(new_entry, confidence_delta=0.08, status=self.PROFILE_STATUS_ACTIVE)
            old_entry = self._meta_entry(profile, key, old_value)
            old_entry["status"] = self.PROFILE_STATUS_STALE
        elif selected == "dismiss":
            mem0_ok = True
            result["mem0_operation"] = "none"
            old_entry = self._meta_entry(profile, key, old_value)
            new_entry = self._meta_entry(profile, key, new_value)
            old_entry["status"] = self.PROFILE_STATUS_ACTIVE
            new_entry["status"] = self.PROFILE_STATUS_ACTIVE
        else:
            return result

        result["mem0_ok"] = mem0_ok
        if not mem0_ok:
            return result

        profile[key] = values
        conflict["status"] = self.CONFLICT_STATUS_RESOLVED
        conflict["resolution"] = selected
        conflict["resolved_at"] = self._utc_now_iso()
        self.write_profile(profile)
        result["ok"] = True
        return result

    def resolve_conflict(self, index: int, action: str) -> bool:
        return bool(self.resolve_conflict_details(index, action).get("ok"))

    def write_profile(self, profile: dict[str, Any]) -> None:
        profile["updated_at"] = self._utc_now_iso()
        self.persistence.write_json(self.profile_file, profile)

    def _build_event_id(self, event_type: str, summary: str, timestamp: str) -> str:
        raw = f"{self._norm_text(event_type)}|{self._norm_text(summary)}|{timestamp[:16]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _coerce_event(
        self,
        raw: dict[str, Any],
        *,
        source_span: list[int],
        channel: str = "",
        chat_id: str = "",
    ) -> dict[str, Any] | None:
        summary = raw.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        event_type = raw.get("type") if isinstance(raw.get("type"), str) else "fact"
        event_type = event_type if event_type in self.EVENT_TYPES else "fact"
        timestamp = raw.get("timestamp") if isinstance(raw.get("timestamp"), str) else self._utc_now_iso()
        salience = min(max(self._safe_float(raw.get("salience"), 0.6), 0.0), 1.0)
        confidence = min(max(self._safe_float(raw.get("confidence"), 0.7), 0.0), 1.0)
        entities = self._to_str_list(raw.get("entities"))
        ttl_days = raw.get("ttl_days")
        if not isinstance(ttl_days, int) or ttl_days <= 0:
            ttl_days = None

        event_id = raw.get("id") if isinstance(raw.get("id"), str) else ""
        if not event_id:
            event_id = self._build_event_id(event_type, summary, timestamp)

        return {
            "id": event_id,
            "timestamp": timestamp,
            "channel": channel,
            "chat_id": chat_id,
            "type": event_type,
            "summary": summary.strip(),
            "entities": entities,
            "salience": salience,
            "confidence": confidence,
            "source_span": source_span,
            "ttl_days": ttl_days,
        }

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
    ) -> list[dict[str, Any]]:
        # mem0-only retrieval path.
        if not self.mem0.enabled:
            return []

        self._record_metric("retrieval_queries", 1)
        retrieved = self.mem0.search(query, top_k=top_k)
        if not retrieved:
            return retrieved
        self._record_metric("retrieval_hits", 1)

        profile = self.read_profile()
        conflicts = profile.get("conflicts", []) if isinstance(profile.get("conflicts"), list) else []

        field_by_event_type = {
            "preference": "preferences",
            "fact": "stable_facts",
            "relationship": "relationships",
            "constraint": "constraints",
            "task": "active_projects",
            "decision": "active_projects",
        }

        resolved_keep_new_old: dict[str, set[str]] = {key: set() for key in self.PROFILE_KEYS}
        resolved_keep_new_new: dict[str, set[str]] = {key: set() for key in self.PROFILE_KEYS}
        for conflict in conflicts:
            if not isinstance(conflict, dict):
                continue
            if str(conflict.get("status", "")).lower() != "resolved":
                continue
            if str(conflict.get("resolution", "")).lower() != "keep_new":
                continue
            field = str(conflict.get("field", ""))
            if field not in resolved_keep_new_old:
                continue
            old_value = str(conflict.get("old", "")).strip()
            new_value = str(conflict.get("new", "")).strip()
            if old_value:
                resolved_keep_new_old[field].add(self._norm_text(old_value))
            if new_value:
                resolved_keep_new_new[field].add(self._norm_text(new_value))

        def _contains_norm_phrase(text: str, phrase_norm: str) -> bool:
            if not phrase_norm:
                return False
            text_norm = self._norm_text(text)
            if not text_norm:
                return False
            return phrase_norm in text_norm

        adjusted: list[dict[str, Any]] = []
        for item in retrieved:
            event_type = str(item.get("type", "fact"))
            field = field_by_event_type.get(event_type)
            summary = str(item.get("summary", ""))
            score = float(item.get("score", 0.0))
            adjustment = 0.0
            adjustment_reasons: list[str] = []

            if field:
                for old_norm in resolved_keep_new_old.get(field, set()):
                    if _contains_norm_phrase(summary, old_norm):
                        adjustment -= 0.18
                        adjustment_reasons.append("resolved_keep_new_old_penalty")
                        break

                for new_norm in resolved_keep_new_new.get(field, set()):
                    if _contains_norm_phrase(summary, new_norm):
                        adjustment += 0.12
                        adjustment_reasons.append("resolved_keep_new_new_boost")
                        break

                section_meta = self._meta_section(profile, field)
                if isinstance(section_meta, dict):
                    for norm_key, meta in section_meta.items():
                        if not isinstance(meta, dict):
                            continue
                        if not _contains_norm_phrase(summary, str(norm_key)):
                            continue
                        status = str(meta.get("status", "")).lower()
                        pinned = bool(meta.get("pinned"))
                        if status == self.PROFILE_STATUS_STALE and not pinned:
                            adjustment -= 0.08
                            adjustment_reasons.append("stale_profile_penalty")
                            break
                        if status == self.PROFILE_STATUS_CONFLICTED:
                            adjustment -= 0.05
                            adjustment_reasons.append("conflicted_profile_penalty")
                            break

            if adjustment_reasons:
                reason = item.get("retrieval_reason")
                if not isinstance(reason, dict):
                    reason = {}
                    item["retrieval_reason"] = reason
                reason["profile_adjustment"] = round(adjustment, 4)
                reason["profile_adjustment_reasons"] = adjustment_reasons

            item["score"] = score + adjustment
            adjusted.append(item)

        adjusted.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return adjusted[: max(1, top_k)]

    def _profile_section_lines(self, profile: dict[str, Any], max_items_per_section: int = 6) -> list[str]:
        lines: list[str] = []
        title_map = {
            "preferences": "Preferences",
            "stable_facts": "Stable Facts",
            "active_projects": "Active Projects",
            "relationships": "Relationships",
            "constraints": "Constraints",
        }
        for key in self.PROFILE_KEYS:
            values = self._to_str_list(profile.get(key))
            if not values:
                continue
            section_meta = self._meta_section(profile, key)
            scored_values: list[tuple[str, float, int]] = []
            for value in values:
                meta = section_meta.get(self._norm_text(value), {}) if isinstance(section_meta, dict) else {}
                status = meta.get("status") if isinstance(meta, dict) else None
                pinned = bool(meta.get("pinned")) if isinstance(meta, dict) else False
                if status == self.PROFILE_STATUS_STALE and not pinned:
                    continue
                conf = self._safe_float(meta.get("confidence") if isinstance(meta, dict) else None, 0.65)
                pin_rank = 1 if pinned else 0
                scored_values.append((value, conf, pin_rank))
            scored_values.sort(key=lambda item: (item[2], item[1]), reverse=True)
            if not scored_values:
                continue
            lines.append(f"### {title_map[key]}")
            for item, confidence, pin_rank in scored_values[:max_items_per_section]:
                pin_suffix = " 📌" if pin_rank else ""
                lines.append(f"- {item} (conf={confidence:.2f}){pin_suffix}")
            lines.append("")
        return lines

    @staticmethod
    def _is_resolved_task_or_decision(summary: str) -> bool:
        text = summary.lower()
        resolved_markers = ("done", "completed", "resolved", "closed", "finished", "cancelled", "canceled")
        return any(marker in text for marker in resolved_markers)

    def _recent_unresolved(self, events: list[dict[str, Any]], max_items: int = 8) -> list[dict[str, Any]]:
        unresolved: list[dict[str, Any]] = []
        for event in reversed(events):
            event_type = str(event.get("type", ""))
            if event_type not in {"task", "decision"}:
                continue
            summary = str(event.get("summary", "")).strip()
            if not summary or self._is_resolved_task_or_decision(summary):
                continue
            unresolved.append(event)
            if len(unresolved) >= max_items:
                break
        unresolved.reverse()
        return unresolved

    def get_memory_context(
        self,
        *,
        query: str | None = None,
        retrieval_k: int = 6,
        token_budget: int = 900,
    ) -> str:
        long_term = self.read_long_term()

        profile = self.read_profile()
        retrieved = self.retrieve(
            query or "",
            top_k=retrieval_k,
        )

        lines: list[str] = ["## Long-term Memory"]
        if long_term:
            lines.append(long_term.strip())

        profile_lines = self._profile_section_lines(profile)
        if profile_lines:
            lines.append("## Profile Memory")
            lines.extend(profile_lines)

        if retrieved:
            lines.append("## Relevant Episodic Memories")
            for item in retrieved:
                timestamp = str(item.get("timestamp", ""))[:16]
                event_type = item.get("type", "fact")
                summary = item.get("summary", "")
                reason = item.get("retrieval_reason", {})
                lines.append(
                    f"- [{timestamp}] ({event_type}) {summary} "
                    f"[sem={reason.get('semantic', 0):.2f}, rec={reason.get('recency', 0):.2f}, src={reason.get('provider', 'mem0')}]"
                )

        unresolved = self._recent_unresolved(self.read_events(limit=60), max_items=6)
        if unresolved:
            lines.append("## Recent Unresolved Tasks/Decisions")
            for item in unresolved:
                ts = str(item.get("timestamp", ""))[:16]
                lines.append(f"- [{ts}] ({item.get('type', 'task')}) {item.get('summary', '')}")

        text = "\n".join(lines).strip()
        max_chars = max(token_budget, 200) * 4
        if len(text) > max_chars:
            text = text[:max_chars].rsplit("\n", 1)[0] + "\n- ... (memory context truncated to token budget)"

        est_tokens = max(1, len(text) // 4) if text else 0
        metrics = self._load_metrics()
        metrics["memory_context_calls"] = int(metrics.get("memory_context_calls", 0)) + 1
        metrics["memory_context_tokens_total"] = int(metrics.get("memory_context_tokens_total", 0)) + est_tokens
        metrics["memory_context_tokens_max"] = max(int(metrics.get("memory_context_tokens_max", 0)), est_tokens)
        metrics["last_updated"] = self._utc_now_iso()
        self.persistence.write_json(self.metrics_file, metrics)
        return text

    def _conflict_pair(self, old_value: str, new_value: str) -> bool:
        old_n = self._norm_text(old_value)
        new_n = self._norm_text(new_value)
        if not old_n or not new_n or old_n == new_n:
            return False
        old_has_not = " not " in f" {old_n} " or "n't" in old_n
        new_has_not = " not " in f" {new_n} " or "n't" in new_n
        if old_has_not == new_has_not:
            return False
        old_tokens = self._tokenize(old_n.replace("not", ""))
        new_tokens = self._tokenize(new_n.replace("not", ""))
        if not old_tokens or not new_tokens:
            return False
        overlap = len(old_tokens & new_tokens) / max(len(old_tokens | new_tokens), 1)
        return overlap >= 0.55

    def _apply_profile_updates(
        self,
        profile: dict[str, Any],
        updates: dict[str, list[str]],
        *,
        enable_contradiction_check: bool,
    ) -> tuple[int, int, int]:
        added = 0
        conflicts = 0
        touched = 0
        profile.setdefault("conflicts", [])

        for key in self.PROFILE_KEYS:
            values = self._to_str_list(profile.get(key))
            seen = {self._norm_text(v) for v in values}
            for candidate in self._to_str_list(updates.get(key)):
                normalized = self._norm_text(candidate)
                if not normalized:
                    continue

                if normalized in seen:
                    entry = self._meta_entry(profile, key, candidate)
                    self._touch_meta_entry(entry, confidence_delta=0.03, status=self.PROFILE_STATUS_ACTIVE)
                    touched += 1
                    continue

                has_conflict = False
                if enable_contradiction_check:
                    for existing in values:
                        if self._conflict_pair(existing, candidate):
                            has_conflict = True
                            old_entry = self._meta_entry(profile, key, existing)
                            self._touch_meta_entry(
                                old_entry,
                                confidence_delta=-0.12,
                                status=self.PROFILE_STATUS_CONFLICTED,
                            )
                            new_entry = self._meta_entry(profile, key, candidate)
                            self._touch_meta_entry(
                                new_entry,
                                confidence_delta=-0.2,
                                min_confidence=0.35,
                                status=self.PROFILE_STATUS_CONFLICTED,
                            )
                            profile["conflicts"].append(
                                {
                                    "timestamp": self._utc_now_iso(),
                                    "field": key,
                                    "old": existing,
                                    "new": candidate,
                                    "old_memory_id": self._find_mem0_id_for_text(existing),
                                    "new_memory_id": self._find_mem0_id_for_text(candidate),
                                    "status": self.CONFLICT_STATUS_OPEN,
                                    "old_confidence": old_entry.get("confidence"),
                                    "new_confidence": new_entry.get("confidence"),
                                }
                            )
                            conflicts += 1
                            touched += 2
                            break

                values.append(candidate)
                seen.add(normalized)
                entry = self._meta_entry(profile, key, candidate)
                if not has_conflict:
                    self._touch_meta_entry(entry, confidence_delta=0.1, status=self.PROFILE_STATUS_ACTIVE)
                    touched += 1
                added += 1

            profile[key] = values

        if conflicts > 0:
            self._record_metric("conflicts_detected", conflicts)
        if added > 0:
            self._record_metric("profile_updates_applied", added)
        return added, conflicts, touched

    def _has_open_conflict(self, profile: dict[str, Any], *, field: str, old_value: str, new_value: str) -> bool:
        old_norm = self._norm_text(old_value)
        new_norm = self._norm_text(new_value)
        for item in profile.get("conflicts", []):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            if status not in {self.CONFLICT_STATUS_OPEN, self.CONFLICT_STATUS_NEEDS_USER}:
                continue
            if item.get("field") != field:
                continue
            if self._norm_text(str(item.get("old", ""))) != old_norm:
                continue
            if self._norm_text(str(item.get("new", ""))) != new_norm:
                continue
            return True
        return False

    def _find_mem0_id_for_text(self, text: str, *, top_k: int = 8) -> str | None:
        target = self._norm_text(text)
        if not target or not self.mem0.enabled:
            return None
        rows = self.mem0.search(text, top_k=top_k)
        if not rows:
            return None

        for row in rows:
            summary = self._norm_text(str(row.get("summary", "")))
            if summary and (summary == target or target in summary or summary in target):
                value = str(row.get("id", "")).strip()
                if value:
                    return value
        value = str(rows[0].get("id", "")).strip()
        return value or None

    def apply_live_user_correction(
        self,
        content: str,
        *,
        channel: str = "",
        chat_id: str = "",
        enable_contradiction_check: bool = True,
    ) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        preference_corrections = self.extractor.extract_explicit_preference_corrections(text)
        fact_corrections = self.extractor.extract_explicit_fact_corrections(text)
        if not preference_corrections and not fact_corrections:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        self._record_metric("user_corrections", len(preference_corrections) + len(fact_corrections))

        profile = self.read_profile()
        profile.setdefault("conflicts", [])
        applied = 0
        conflicts = 0
        events: list[dict[str, Any]] = []

        def _apply_field_corrections(
            *,
            field: str,
            event_type: str,
            correction_label: str,
            correction_pairs: list[tuple[str, str]],
        ) -> tuple[int, int]:
            local_applied = 0
            local_conflicts = 0
            values = self._to_str_list(profile.get(field))
            by_norm = {self._norm_text(v): v for v in values}

            for new_value, old_value in correction_pairs:
                old_norm = self._norm_text(old_value)
                new_norm = self._norm_text(new_value)
                if not new_norm:
                    continue

                if new_norm not in by_norm:
                    values.append(new_value)
                    by_norm[new_norm] = new_value
                    local_applied += 1

                new_entry = self._meta_entry(profile, field, by_norm[new_norm])
                self._touch_meta_entry(new_entry, confidence_delta=0.08, status=self.PROFILE_STATUS_ACTIVE)

                if enable_contradiction_check and old_norm in by_norm and not self._has_open_conflict(
                    profile,
                    field=field,
                    old_value=by_norm[old_norm],
                    new_value=by_norm[new_norm],
                ):
                    old_entry = self._meta_entry(profile, field, by_norm[old_norm])
                    self._touch_meta_entry(
                        old_entry,
                        confidence_delta=-0.2,
                        min_confidence=0.35,
                        status=self.PROFILE_STATUS_CONFLICTED,
                    )
                    self._touch_meta_entry(
                        new_entry,
                        confidence_delta=-0.08,
                        min_confidence=0.35,
                        status=self.PROFILE_STATUS_CONFLICTED,
                    )
                    profile["conflicts"].append(
                        {
                            "timestamp": self._utc_now_iso(),
                            "field": field,
                            "old": by_norm[old_norm],
                            "new": by_norm[new_norm],
                            "old_memory_id": self._find_mem0_id_for_text(by_norm[old_norm]),
                            "new_memory_id": self._find_mem0_id_for_text(by_norm[new_norm]),
                            "status": self.CONFLICT_STATUS_OPEN,
                            "old_confidence": old_entry.get("confidence"),
                            "new_confidence": new_entry.get("confidence"),
                            "source": "live_correction",
                        }
                    )
                    local_conflicts += 1

                event = self._coerce_event(
                    {
                        "timestamp": self._utc_now_iso(),
                        "type": event_type,
                        "summary": f"User corrected {correction_label}: {new_value} (not {old_value}).",
                        "entities": [new_value, old_value],
                        "salience": 0.85,
                        "confidence": 0.9,
                        "ttl_days": 365,
                    },
                    source_span=[0, 0],
                    channel=channel,
                    chat_id=chat_id,
                )
                if event:
                    events.append(event)

            profile[field] = values
            return local_applied, local_conflicts

        pref_applied, pref_conflicts = _apply_field_corrections(
            field="preferences",
            event_type="preference",
            correction_label="preference",
            correction_pairs=preference_corrections,
        )
        fact_applied, fact_conflicts = _apply_field_corrections(
            field="stable_facts",
            event_type="fact",
            correction_label="fact",
            correction_pairs=fact_corrections,
        )
        applied += pref_applied + fact_applied
        conflicts += pref_conflicts + fact_conflicts

        if not applied and not conflicts:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        profile["last_verified_at"] = self._utc_now_iso()
        self.write_profile(profile)

        events_written = self.append_events(events)
        if events_written > 0:
            self._record_metric("events_extracted", events_written)

        if applied > 0:
            self._record_metric("profile_updates_applied", applied)
        if conflicts > 0:
            self._record_metric("conflicts_detected", conflicts)

        needs_user = 0
        question: str | None = None
        if conflicts > 0:
            resolution = self.auto_resolve_conflicts(max_items=10)
            needs_user = int(resolution.get("needs_user", 0))
            if needs_user > 0:
                question = self.ask_user_for_conflict()

        if self.mem0.enabled:
            self.mem0.add_text(
                text,
                metadata={
                    "event_type": "user_correction",
                    "timestamp": self._utc_now_iso(),
                    "channel": channel,
                    "chat_id": chat_id,
                },
            )

        self.rebuild_memory_snapshot(write=True)
        return {
            "applied": applied,
            "conflicts": conflicts,
            "events": events_written,
            "needs_user": needs_user,
            "question": question,
        }

    def read_long_term(self) -> str:
        return self.persistence.read_text(self.memory_file)

    def write_long_term(self, content: str) -> None:
        self.persistence.write_text(self.memory_file, content)

    def append_history(self, entry: str) -> None:
        self.persistence.append_text(self.history_file, entry.rstrip() + "\n\n")

    def rebuild_memory_snapshot(self, *, max_events: int = 30, write: bool = True) -> str:
        profile = self.read_profile()
        events = self.read_events(limit=max_events)

        parts = ["# Memory", ""]
        section_lines = self._profile_section_lines(profile, max_items_per_section=8)
        if section_lines:
            parts.extend(section_lines)

        unresolved = self._recent_unresolved(events, max_items=6)
        if unresolved:
            parts.append("## Open Tasks & Decisions")
            for event in unresolved:
                ts = str(event.get("timestamp", ""))[:16]
                parts.append(f"- [{ts}] ({event.get('type', 'task')}) {event.get('summary', '')}")
            parts.append("")

        if events:
            parts.append("## Recent Episodic Highlights")
            for event in events[-max_events:]:
                ts = str(event.get("timestamp", ""))[:16]
                parts.append(f"- [{ts}] ({event.get('type', 'fact')}) {event.get('summary', '')}")
        snapshot = "\n".join(parts).strip() + "\n"
        if write:
            self.write_long_term(snapshot)
        return snapshot

    def verify_memory(self, *, stale_days: int = 90, update_profile: bool = False) -> dict[str, Any]:
        profile = self.read_profile()
        events = self.read_events()
        now = datetime.now(timezone.utc)
        stale = 0
        total_ttl = 0
        for event in events:
            ttl_days = event.get("ttl_days")
            timestamp = self._to_datetime(str(event.get("timestamp", "")))
            if not timestamp:
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age_days = (now - timestamp).total_seconds() / 86400.0
            if isinstance(ttl_days, int) and ttl_days > 0:
                total_ttl += 1
                if age_days > ttl_days:
                    stale += 1
            elif age_days > stale_days:
                stale += 1

        stale_profile_items = 0
        profile_touched = False
        for key in self.PROFILE_KEYS:
            section_meta = self._meta_section(profile, key)
            for _, entry in section_meta.items():
                if not isinstance(entry, dict):
                    continue
                last_seen = self._to_datetime(str(entry.get("last_seen_at", "")))
                if not last_seen:
                    continue
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                age_days = max((now - last_seen).total_seconds() / 86400.0, 0.0)
                if age_days > stale_days:
                    stale_profile_items += 1
                    if update_profile and entry.get("status") != self.PROFILE_STATUS_STALE:
                        entry["status"] = self.PROFILE_STATUS_STALE
                        profile_touched = True

        if update_profile:
            profile["last_verified_at"] = self._utc_now_iso()
            profile_touched = True
            if profile_touched:
                self.write_profile(profile)

        open_conflicts = [
            c
            for c in profile.get("conflicts", [])
            if isinstance(c, dict)
            and str(c.get("status", self.CONFLICT_STATUS_OPEN)).strip().lower()
            in {self.CONFLICT_STATUS_OPEN, self.CONFLICT_STATUS_NEEDS_USER}
        ]
        report = {
            "events": len(events),
            "profile_items": sum(len(self._to_str_list(profile.get(k))) for k in self.PROFILE_KEYS),
            "open_conflicts": len(open_conflicts),
            "stale_events": stale,
            "stale_profile_items": stale_profile_items,
            "ttl_tracked_events": total_ttl,
            "last_verified_at": profile.get("last_verified_at"),
        }
        return report

    def _select_messages_for_consolidation(
        self,
        session: Session,
        *,
        archive_all: bool,
        memory_window: int,
    ) -> tuple[list[dict[str, Any]], int, int] | None:
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            source_start = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
            return old_messages, keep_count, source_start

        keep_count = memory_window // 2
        if len(session.messages) <= keep_count:
            return None
        if len(session.messages) - session.last_consolidated <= 0:
            return None
        old_messages = session.messages[session.last_consolidated:-keep_count]
        source_start = session.last_consolidated
        if not old_messages:
            return None
        logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)
        return old_messages, keep_count, source_start

    @staticmethod
    def _format_conversation_lines(old_messages: list[dict[str, Any]]) -> list[str]:
        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")
        return lines

    @staticmethod
    def _build_consolidation_prompt(current_memory: str, lines: list[str]) -> str:
        return f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

    def _record_consolidation_input_metrics(self, old_messages: list[dict[str, Any]]) -> None:
        user_messages = [m for m in old_messages if str(m.get("role", "")).lower() == "user"]
        user_corrections = self.extractor.count_user_corrections(old_messages)
        self._record_metrics(
            {
                "messages_processed": len(old_messages),
                "user_messages_processed": len(user_messages),
                "user_corrections": user_corrections,
            }
        )

    def _apply_save_memory_tool_result(self, *, args: dict[str, Any], current_memory: str) -> None:
        if entry := args.get("history_entry"):
            if not isinstance(entry, str):
                entry = json.dumps(entry, ensure_ascii=False)
            self.append_history(entry)
        if update := args.get("memory_update"):
            if not isinstance(update, str):
                update = json.dumps(update, ensure_ascii=False)
            if update != current_memory:
                self.write_long_term(update)

    def _finalize_consolidation(self, session: Session, *, archive_all: bool, keep_count: int) -> None:
        session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
        self._record_metric("consolidations", 1)
        logger.debug("Memory KPI snapshot: {}", self.get_observability_report().get("kpis", {}))
        logger.info(
            "Memory consolidation done: {} messages, last_consolidated={}",
            len(session.messages),
            session.last_consolidated,
        )

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
        enable_contradiction_check: bool = True,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Returns True on success (including no-op), False on failure.
        """
        selection = self._select_messages_for_consolidation(
            session,
            archive_all=archive_all,
            memory_window=memory_window,
        )
        if selection is None:
            return True
        old_messages, keep_count, source_start = selection

        lines = self._format_conversation_lines(old_messages)

        current_memory = self.read_long_term()
        prompt = self._build_consolidation_prompt(current_memory, lines)

        try:
            self._record_consolidation_input_metrics(old_messages)

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

            args = self.extractor.parse_tool_args(response.tool_calls[0].arguments)
            if not args:
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            self._apply_save_memory_tool_result(args=args, current_memory=current_memory)

            profile = self.read_profile()
            events, profile_updates = await self.extractor.extract_structured_memory(
                provider,
                model,
                profile,
                lines,
                old_messages,
                source_start=source_start,
            )
            events_written = self.append_events(events)
            profile_added, _, profile_touched = self._apply_profile_updates(
                profile,
                profile_updates,
                enable_contradiction_check=enable_contradiction_check,
            )
            if events_written > 0 or profile_added > 0 or profile_touched > 0:
                profile["last_verified_at"] = self._utc_now_iso()
                self.write_profile(profile)
                self._record_metric("events_extracted", events_written)

            if profile_added > 0:
                self.auto_resolve_conflicts(max_items=10)

            self.rebuild_memory_snapshot(write=True)

            if self.mem0.enabled:
                for m in old_messages:
                    role = str(m.get("role", "user")).strip().lower() or "user"
                    content = str(m.get("content", "")).strip()
                    if not content:
                        continue
                    self.mem0.add_text(
                        content,
                        metadata={
                            "event_type": "conversation_turn",
                            "role": role,
                            "timestamp": str(m.get("timestamp", "")),
                            "session": session.key,
                        },
                    )

            self._finalize_consolidation(
                session,
                archive_all=archive_all,
                keep_count=keep_count,
            )
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
