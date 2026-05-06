"""Helpers for lightweight local-memory read/write integration.

Designed to be small and cherry-pick friendly on top of nightly.
The integration is MCP-server-name based, so machine-specific command/path
configuration remains in local config rather than tracked code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.agent.tools.registry import ToolRegistry


_LOCAL_MEMORY_SERVER_NAME = "local_memory"

_OPERATIONAL_KEYWORDS = (
    "runbook",
    "workflow",
    "service",
    "systemd",
    "listener",
    "port",
    "gateway",
    "proxy",
    "restart",
    "recover",
    "recovery",
    "health",
    "repo",
    "branch",
    "parity",
    "path",
    "config",
    "certificate",
    "exchange",
    "sharepoint",
    "atera",
    "orchestrator",
    "approval",
    "policy",
    "memory",
)

_PREFERENCE_KEYWORDS = (
    "prefer",
    "preference",
    "preferred",
    "usually",
    "always",
    "never",
    "style",
    "tone",
    "format",
    "remember",
    "call me",
    "i like",
    "i want",
)

_PROJECT_KEYWORDS = (
    "project",
    "workspace",
    "codebase",
    "repository",
    "repo",
    "roadmap",
    "plan",
    "milestone",
    "next step",
    "todo",
    "task",
    "continue",
)


@dataclass(slots=True)
class LocalMemoryConfig:
    enabled: bool = False
    server_name: str = _LOCAL_MEMORY_SERVER_NAME
    search_first: bool = True
    auto_capture_candidates: bool = False
    max_search_results: int = 3
    min_query_length: int = 12
    max_candidate_chars: int = 1200
    max_context_chars: int = 1600
    enable_bootstrap_recall: bool = True


@dataclass(slots=True)
class LocalMemoryInjection:
    heading: str
    content: str


@dataclass(slots=True)
class LocalMemoryCaptureRequest:
    type: str = "procedure"
    domain: str = "operations"
    title: str = ""
    summary: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    record_id: str | None = None


def has_local_memory_server(tool_registry: ToolRegistry, server_name: str = _LOCAL_MEMORY_SERVER_NAME) -> bool:
    return any(
        tool_registry.has(name)
        for name in _flat_tool_name_candidates(server_name, "search", "build_context")
    )


def should_search_local_memory(user_text: str, cfg: LocalMemoryConfig) -> bool:
    text = (user_text or "").strip().lower()
    if not cfg.enabled or not cfg.search_first:
        return False
    if not text:
        return False
    if len(text) < cfg.min_query_length and not _is_bootstrap_recall_query(text):
        return False
    return _classify_memory_query(text) is not None


async def search_local_memory(
    tool_registry: ToolRegistry,
    user_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryInjection | None:
    build_tool_name = _resolve_tool_name(tool_registry, cfg.server_name, "build_context")
    search_tool_name = _resolve_tool_name(tool_registry, cfg.server_name, "search")

    query_kind = _classify_memory_query(user_text)

    if build_tool_name:
        params = {
            "query": _build_context_query(user_text, query_kind),
            "include_candidates": False,
            "limit": max(1, cfg.max_search_results),
            "max_chars": max(200, cfg.max_context_chars),
        }
        try:
            result = await tool_registry.execute(build_tool_name, params)
        except Exception:
            logger.exception("Local memory context build failed")
        else:
            rendered = _render_context_result(result)
            if rendered:
                return LocalMemoryInjection(
                    heading="Supplemental local-memory recall",
                    content=rendered,
                )

    if not search_tool_name:
        return None

    params = {
        "query": _build_context_query(user_text, query_kind),
        "include_candidates": True,
        "limit": max(1, cfg.max_search_results),
    }
    try:
        result = await tool_registry.execute(search_tool_name, params)
    except Exception:
        logger.exception("Local memory search failed")
        return None

    rendered = _render_search_result(result)
    if not rendered:
        return None
    return LocalMemoryInjection(
        heading="Supplemental local-memory recall",
        content=rendered,
    )


def _flat_tool_name_candidates(server_name: str, operation: str, *aliases: str) -> list[str]:
    ops = (operation, *aliases)
    return [f"mcp_{server_name}_memory_{op}" for op in ops]


def _resolve_tool_name(tool_registry: ToolRegistry, server_name: str, operation: str, *aliases: str) -> str | None:
    for candidate in _flat_tool_name_candidates(server_name, operation, *aliases):
        if tool_registry.has(candidate):
            return candidate
    return None


def _is_bootstrap_recall_query(text: str) -> bool:
    return any(phrase in text for phrase in ("continue", "pick up", "resume", "what next", "where were we"))


def _classify_memory_query(user_text: str) -> str | None:
    text = (user_text or "").strip().lower()
    if not text:
        return None
    if any(keyword in text for keyword in _PREFERENCE_KEYWORDS):
        return "preferences"
    if any(keyword in text for keyword in _PROJECT_KEYWORDS):
        return "project"
    if any(keyword in text for keyword in _OPERATIONAL_KEYWORDS):
        return "operations"
    if _is_bootstrap_recall_query(text):
        return "project"
    return None


def _build_context_query(user_text: str, query_kind: str | None) -> str:
    raw = (user_text or "").strip()
    text = raw[:400]
    if query_kind == "preferences":
        return (
            f"user preferences, response style, operating preferences, personalization\n"
            f"{text}"
        ).strip()
    if query_kind == "project":
        return (
            f"active project context, current plan, next steps, workspace state\n"
            f"{text}"
        ).strip()
    if query_kind == "operations":
        return (
            f"operational runbooks, procedures, environment details\n"
            f"{text}"
        ).strip()
    return text


def should_capture_candidate(
    user_text: str,
    assistant_text: str | None,
    cfg: LocalMemoryConfig,
) -> bool:
    if not cfg.enabled or not cfg.auto_capture_candidates:
        return False
    if not assistant_text:
        return False
    text = assistant_text.lower()
    if len(assistant_text.strip()) < 80:
        return False
    if any(secret_word in text for secret_word in ("token", "password", "secret", "apikey", "api key")):
        return False
    return any(keyword in user_text.lower() for keyword in _OPERATIONAL_KEYWORDS)


def build_capture_request(
    user_text: str,
    assistant_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryCaptureRequest | None:
    cleaned = _strip_markdown(assistant_text).strip()
    if not cleaned:
        return None
    cleaned = cleaned[: cfg.max_candidate_chars].strip()
    summary = _first_sentence(cleaned, limit=240)
    title = _derive_title(user_text, cleaned)
    tags = _derive_tags(user_text, cleaned)
    return LocalMemoryCaptureRequest(
        type=_derive_type(user_text, cleaned),
        domain=_derive_domain(user_text, cleaned),
        title=title,
        summary=summary,
        content=cleaned,
        tags=tags,
        metadata={"source": "conversation", "integration": "nanobot-bolt-on-local-memory"},
    )


async def capture_candidate(
    tool_registry: ToolRegistry,
    request: LocalMemoryCaptureRequest,
    cfg: LocalMemoryConfig,
) -> None:
    tool_name = _resolve_tool_name(tool_registry, cfg.server_name, "capture_candidate")
    if not tool_name:
        return
    params = {
        "type": request.type,
        "domain": request.domain,
        "title": request.title,
        "summary": request.summary,
        "content": request.content,
        "tags": request.tags,
        "metadata": request.metadata,
        "record_id": request.record_id,
    }
    try:
        await tool_registry.execute(tool_name, params)
    except Exception:
        logger.exception("Local memory candidate capture failed")


async def forget_local_memory(
    tool_registry: ToolRegistry,
    query: str,
    cfg: LocalMemoryConfig,
) -> bool:
    search_tool = _resolve_tool_name(tool_registry, cfg.server_name, "search")
    deprecate_tool = _resolve_tool_name(tool_registry, cfg.server_name, "deprecate")
    if not search_tool or not deprecate_tool:
        return False

    try:
        result = await tool_registry.execute(
            search_tool,
            {
                "query": query,
                "limit": 5,
                "include_candidates": True,
                "include_deprecated": False,
                "domain": None,
                "type": None,
            },
        )
    except Exception:
        logger.exception("Local memory forget search failed")
        return False

    matches = _extract_matches(result)
    if not matches:
        return False

    record_id = _match_record_id(query, matches)
    if not record_id:
        return False

    try:
        await tool_registry.execute(
            deprecate_tool,
            {
                "record_id": record_id,
                "reason": _forget_reason(query, matches, record_id),
                "deprecated_by": "user_request",
            },
        )
        return True
    except Exception:
        logger.exception("Local memory forget deprecate failed")
        return False


def _extract_matches(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    data = result
    if isinstance(result, str):
        try:
            data = json.loads(result)
        except Exception:
            return []
    elif not isinstance(result, (dict, list)):
        try:
            data = json.loads(str(result))
        except Exception:
            return []

    if isinstance(data, dict):
        for key in ("results", "matches", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


_STOP_WORDS = {
    "the",
    "a",
    "an",
    "this",
    "that",
    "on",
    "for",
    "to",
    "of",
    "and",
    "uses",
    "use",
    "using",
    "preferred",
    "preference",
    "host",
    "remotes",
    "remote",
    "authentication",
    "auth",
    "operations",
    "operation",
}


def _tokenize_text(text: str) -> set[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return set()
    return {token for token in normalized.split() if token and token not in _STOP_WORDS}


def _is_semantic_duplicate(
    query: str,
    left_title: str,
    left_summary: str,
    right_title: str,
    right_summary: str,
) -> bool:
    left_tokens = _tokenize_text(f"{left_title} {left_summary}")
    right_tokens = _tokenize_text(f"{right_title} {right_summary}")
    query_tokens = _tokenize_text(query)
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    if query_tokens and not (query_tokens & overlap):
        return False
    if left_tokens == right_tokens:
        return True
    if query_tokens and len(query_tokens & overlap) >= 2:
        return True
    if union and (len(overlap) / len(union)) >= 0.5:
        return True
    return False


def _match_record_id(query: str, matches: list[dict[str, Any]]) -> str | None:
    needle = query.strip().lower()
    if not needle:
        return None

    exact_title_matches: list[str] = []
    partial_matches: list[str] = []
    duplicate_candidates: dict[tuple[str, str], list[str]] = {}
    semantic_items: list[tuple[str, str, str]] = []

    for item in matches:
        record_id = item.get("record_id") or item.get("id")
        if not isinstance(record_id, str) or not record_id.strip():
            continue
        record_id = record_id.strip()
        title = str(item.get("title") or item.get("name") or "").strip()
        summary = str(item.get("summary") or item.get("content") or "").strip()
        lowered_title = title.lower()
        lowered_summary = summary.lower()

        key = (lowered_title, lowered_summary)
        duplicate_candidates.setdefault(key, []).append(record_id)
        semantic_items.append((record_id, title, summary))

        if needle == lowered_title and record_id not in exact_title_matches:
            exact_title_matches.append(record_id)
        elif needle in lowered_title or needle in lowered_summary:
            partial_matches.append(record_id)

    for ids in duplicate_candidates.values():
        if len(ids) > 1:
            return ids[-1]

    for i, (record_id, title, summary) in enumerate(semantic_items):
        for other_id, other_title, other_summary in semantic_items[i + 1 :]:
            if _is_semantic_duplicate(query, title, summary, other_title, other_summary):
                return other_id

    if exact_title_matches:
        return exact_title_matches[-1]
    if partial_matches:
        return partial_matches[0]

    first = matches[0].get("record_id") or matches[0].get("id")
    if isinstance(first, str) and first.strip():
        return first.strip()
    return None


def _forget_reason(query: str, matches: list[dict[str, Any]], record_id: str) -> str:
    needle = query.strip().lower()
    selected: dict[str, Any] | None = None
    duplicates = 0
    semantic_records: list[tuple[str, str, str]] = []
    for item in matches:
        item_id = item.get("record_id") or item.get("id")
        if item_id == record_id:
            selected = item
        title = str(item.get("title") or item.get("name") or "").strip()
        summary = str(item.get("summary") or item.get("content") or "").strip()
        lowered_title = title.lower()
        lowered_summary = summary.lower()
        if isinstance(item_id, str) and item_id.strip():
            semantic_records.append((item_id.strip(), title, summary))
        if needle and (needle == lowered_title or needle in lowered_title or needle in lowered_summary):
            duplicates += 1

    semantic_duplicate_count = 0
    for i, (_, title, summary) in enumerate(semantic_records):
        for _, other_title, other_summary in semantic_records[i + 1 :]:
            if _is_semantic_duplicate(query, title, summary, other_title, other_summary):
                semantic_duplicate_count += 1

    if duplicates > 1 or semantic_duplicate_count > 0:
        return f"User requested forget/dedup for query: {query[:160]}"
    if selected is not None:
        title = str(selected.get("title") or selected.get("name") or "").strip()
        if title:
            return f"User requested forget: {title[:160]}"
    return f"User requested forget: {query[:160]}"


def _render_context_result(result: Any) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        text = result.strip()
        return text if text else None
    try:
        data = result if isinstance(result, dict) else json.loads(str(result))
    except Exception:
        return str(result).strip() or None
    if isinstance(data, dict):
        context = data.get("context")
        if isinstance(context, str) and context.strip():
            return context.strip()
        return _render_search_result(data)
    return _render_search_result(data)


def _render_search_result(result: Any) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        text = result.strip()
        return text if text else None
    try:
        data = result if isinstance(result, (dict, list)) else json.loads(str(result))
    except Exception:
        return str(result).strip() or None

    if isinstance(data, dict):
        for key in ("results", "matches", "items"):
            if isinstance(data.get(key), list):
                lines = [_render_match(item) for item in data[key][:5]]
                lines = [line for line in lines if line]
                return "\n".join(lines) if lines else None
        return json.dumps(data, ensure_ascii=False)
    if isinstance(data, list):
        lines = [_render_match(item) for item in data[:5]]
        lines = [line for line in lines if line]
        return "\n".join(lines) if lines else None
    return str(data).strip() or None


def _render_match(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, dict):
        return str(item).strip() or None
    title = str(item.get("title") or item.get("name") or "memory").strip()
    summary = str(item.get("summary") or item.get("content") or "").strip()
    summary = re.sub(r"\s+", " ", summary)
    if len(summary) > 240:
        summary = summary[:237].rstrip() + "..."
    if not summary:
        return title
    return f"- {title}: {summary}"


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def _first_sentence(text: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    match = re.search(r"[.!?]", compact)
    if match and match.end() <= limit:
        return compact[: match.end()].strip()
    return compact[: limit - 3].rstrip() + "..."


def _derive_title(user_text: str, assistant_text: str) -> str:
    base = re.sub(r"\s+", " ", user_text).strip()
    if not base:
        base = assistant_text[:80].strip()
    if len(base) > 80:
        base = base[:77].rstrip() + "..."
    return base


def _derive_type(user_text: str, assistant_text: str) -> str:
    haystack = f"{user_text} {assistant_text}".lower()
    if any(word in haystack for word in ("policy", "approval", "rule")):
        return "policy"
    if any(word in haystack for word in ("architecture", "design", "decision")):
        return "decision"
    if any(word in haystack for word in ("fact", "host", "path", "port", "url", "workspace")):
        return "fact"
    return "procedure"


def _derive_domain(user_text: str, assistant_text: str) -> str:
    haystack = f"{user_text} {assistant_text}".lower()
    if any(word in haystack for word in ("graphify", "repo", "branch", "workspace", "git")):
        return "engineering"
    if any(word in haystack for word in ("microsoft", "exchange", "sharepoint", "teams", "atera")):
        return "it-ops"
    return "operations"


def _derive_tags(user_text: str, assistant_text: str) -> list[str]:
    haystack = f"{user_text} {assistant_text}".lower()
    tags: list[str] = []
    for keyword in _OPERATIONAL_KEYWORDS:
        if keyword in haystack:
            tags.append(keyword.replace(" ", "_"))
    seen: set[str] = set()
    deduped: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped[:12]
