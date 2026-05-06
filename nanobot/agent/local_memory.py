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
    "my name",
    "username",
    "favorite",
    "favourite",
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
    "active project",
    "current work",
    "what were we doing",
    "where were we",
)

_PERSONAL_FACT_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("user_identity", "profile", ("call me ", "my name is ", "my full name is ", "my username is ", "username is ")),
    ("user_preference", "profile", ("my favorite ", "my favourite ", "i like ", "i prefer ", "you can call me ")),
    ("interaction_preference", "profile", ("don't ask ", "do not ask ", "stop asking ", "i prefer ", "please be ", "be more ", "be less ")),
    ("relationship_context", "profile", ("my son ", "my daughter ", "my wife ", "my husband ", "my family ", "my mom ", "my mother ", "my dad ", "my father ")),
    ("user_health_fact", "profile", ("i had ", "i have ", "i'm allergic ", "i am allergic ", "diagnosed with ", "heart attack", "stroke", "surgery")),
)

_SENSITIVE_PERSONAL_TERMS = (
    "heart attack",
    "stroke",
    "allergic",
    "allergy",
    "diagnosed",
    "hospital",
    "medical",
    "health",
    "surgery",
)


@dataclass(slots=True)
class LocalMemoryConfig:
    enabled: bool = False
    server_name: str = _LOCAL_MEMORY_SERVER_NAME
    search_first: bool = True
    auto_capture_candidates: bool = False
    auto_capture_personal_facts: bool = True
    auto_capture_session_summaries: bool = True
    max_search_results: int = 3
    min_query_length: int = 12
    max_candidate_chars: int = 1200
    max_context_chars: int = 1600
    session_summary_max_chars: int = 900
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


@dataclass(slots=True)
class SessionSummaryCapture:
    summary_text: str
    query_kind: str | None


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


def build_session_summary_capture(
    user_text: str,
    assistant_text: str,
    cfg: LocalMemoryConfig,
) -> SessionSummaryCapture | None:
    if not cfg.auto_capture_session_summaries:
        return None
    cleaned_user = _strip_markdown(user_text).strip()
    cleaned_assistant = _strip_markdown(assistant_text).strip()
    if not cleaned_user or not cleaned_assistant:
        return None
    if len(cleaned_assistant) < 120:
        return None
    if any(secret_word in cleaned_assistant.lower() for secret_word in ("token", "password", "secret", "apikey", "api key")):
        return None
    query_kind = _classify_memory_query(cleaned_user)
    if query_kind is None:
        return None
    bullets = [
        f"User request: {_compact_text(cleaned_user, 220)}",
        f"Assistant outcome: {_compact_text(cleaned_assistant, 420)}",
    ]
    summary_text = "\n".join(f"- {line}" for line in bullets if line)
    summary_text = summary_text[: cfg.session_summary_max_chars].strip()
    if len(summary_text) < 80:
        return None
    return SessionSummaryCapture(summary_text=summary_text, query_kind=query_kind)



def build_session_summary_capture_request(
    user_text: str,
    assistant_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryCaptureRequest | None:
    capture = build_session_summary_capture(user_text, assistant_text, cfg)
    if capture is None:
        return None
    return build_session_summary_capture_request_from_summary(
        capture.summary_text,
        capture.query_kind,
        cfg,
    )



def build_session_summary_capture_request_from_summary(
    summary_text: str,
    query_kind: str | None,
    cfg: LocalMemoryConfig,
) -> LocalMemoryCaptureRequest | None:
    cleaned_summary = _strip_markdown(summary_text).strip()
    if not cleaned_summary:
        return None
    cleaned_summary = cleaned_summary[: cfg.session_summary_max_chars].strip()
    if len(cleaned_summary) < 80:
        return None
    domain = {
        "preferences": "profile",
        "project": "projects",
        "operations": "operations",
    }.get(query_kind or "", "operations")
    kind_label = {
        "preferences": "preference",
        "project": "project",
        "operations": "operations",
    }.get(query_kind or "", "general")
    title = f"Session summary: {kind_label}"
    summary = _first_sentence(cleaned_summary.replace("\n", " "), limit=220)
    return LocalMemoryCaptureRequest(
        type="session_summary",
        domain=domain,
        title=title,
        summary=summary,
        content=cleaned_summary,
        tags=["session-summary", kind_label, "candidate"],
        metadata={
            "source": "nanobot-session-summary",
            "query_kind": query_kind,
            "review_status": "unreviewed",
            "trust_level": "candidate",
            "capture_phase": "session-reset",
        },
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
    return any(
        phrase in text
        for phrase in (
            "continue",
            "pick up",
            "resume",
            "what next",
            "where were we",
            "what were we doing",
            "current work",
            "active project",
        )
    )


def _is_profile_resume_query(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "what's my name",
            "what is my name",
            "what should you call me",
            "what should i be called",
            "what's my username",
            "what is my username",
            "what do you know about me",
            "who am i",
            "my preferred name",
        )
    )


def _classify_memory_query(user_text: str) -> str | None:
    text = (user_text or "").strip().lower()
    if not text:
        return None
    if _is_profile_resume_query(text):
        return "preferences"
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
            f"user preferences, response style, operating preferences, personalization, profile facts, preferred name, username, favorites\n"
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



def _compact_text(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


def should_capture_candidate(
    user_text: str,
    assistant_text: str | None,
    cfg: LocalMemoryConfig,
) -> bool:
    if not cfg.enabled:
        return False
    lowered_user = user_text.lower()
    if cfg.auto_capture_personal_facts and is_personal_fact_statement(user_text):
        return True
    if cfg.auto_capture_session_summaries and assistant_text:
        session_summary = build_session_summary_capture(user_text, assistant_text, cfg)
        if session_summary is not None:
            return True
    if not cfg.auto_capture_candidates:
        return False
    if not assistant_text:
        return False
    text = assistant_text.lower()
    if len(assistant_text.strip()) < 80:
        return False
    if any(secret_word in text for secret_word in ("token", "password", "secret", "apikey", "api key")):
        return False
    return any(keyword in lowered_user for keyword in _OPERATIONAL_KEYWORDS)


def build_capture_request(
    user_text: str,
    assistant_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryCaptureRequest | None:
    personal_fact = build_personal_fact_capture_request(user_text, cfg)
    if personal_fact is not None:
        return personal_fact
    session_summary = build_session_summary_capture_request(user_text, assistant_text, cfg)
    if session_summary is not None:
        return session_summary
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
                return _render_match_list(data[key])
        return json.dumps(data, ensure_ascii=False)
    if isinstance(data, list):
        return _render_match_list(data)
    return str(data).strip() or None


def _render_match_list(items: list[Any]) -> str | None:
    ranked = sorted(items[:20], key=_match_priority, reverse=True)
    lines = [_render_match(item) for item in ranked[:5]]
    lines = [line for line in lines if line]
    return "\n".join(lines) if lines else None


def _match_priority(item: Any) -> tuple[int, int, int]:
    if not isinstance(item, dict):
        return (0, 0, 0)
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    profile_fields = metadata.get("profile_fields") if isinstance(metadata.get("profile_fields"), dict) else {}
    title = str(item.get("title") or item.get("name") or "").lower()
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    lowered_tags = {str(tag).lower() for tag in tags}
    is_profile = 1 if (item.get("domain") == "profile" or "profile" in lowered_tags or profile_fields) else 0
    is_identity = 1 if ({"identity", "preferred_name", "username", "preference"} & lowered_tags or "preferred name" in title or "username" in title) else 0
    field_count = len(profile_fields)
    return (is_profile, is_identity, field_count)


def _render_match(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, dict):
        return str(item).strip() or None
    title = str(item.get("title") or item.get("name") or "memory").strip()
    summary = str(item.get("summary") or item.get("content") or "").strip()
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    profile_fields = metadata.get("profile_fields") if isinstance(metadata.get("profile_fields"), dict) else {}
    if profile_fields:
        preferred_name = profile_fields.get("preferred_name")
        username = profile_fields.get("username")
        favorite_food = profile_fields.get("favorite_food")
        if preferred_name and title.lower() == "user preferred name":
            summary = f"Preferred name: {preferred_name}"
        elif username and title.lower() == "user username":
            summary = f"Username: {username}"
        elif favorite_food and title.lower() == "user preference":
            summary = f"Favorite food: {favorite_food}"
    summary = re.sub(r"\s+", " ", summary)
    if len(summary) > 240:
        summary = summary[:237].rstrip() + "..."
    if not summary:
        return title
    return f"- {title}: {summary}"


def is_personal_fact_statement(user_text: str) -> bool:
    lowered = user_text.strip().lower()
    if not lowered:
        return False
    for _memory_type, _domain, patterns in _PERSONAL_FACT_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return True
    return False


def build_personal_fact_capture_request(
    user_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryCaptureRequest | None:
    if not cfg.auto_capture_personal_facts:
        return None
    normalized = _normalize_personal_fact_text(user_text)
    if not normalized:
        return None
    lowered = normalized.lower()
    extracted_fields = _extract_personal_fact_fields(normalized)
    memory_type = "user_profile_fact"
    domain = "profile"
    tags = ["personal", "profile"]
    title = "Personal fact"
    summary = normalized[:240]
    attributes: dict[str, Any] = {
        "source": "user_stated",
        "integration": "nanobot-bolt-on-local-memory",
        "profile_fields": extracted_fields,
    }

    for candidate_type, candidate_domain, patterns in _PERSONAL_FACT_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            memory_type = candidate_type
            domain = candidate_domain
            break

    if "call me " in lowered or "my name is " in lowered or "you can call me " in lowered:
        title = "User preferred name"
        tags.extend(["identity", "preferred_name"])
        if extracted_fields.get("preferred_name"):
            summary = f"Preferred name: {extracted_fields['preferred_name']}"
    elif "username" in lowered:
        title = "User username"
        tags.extend(["identity", "username"])
        if extracted_fields.get("username"):
            summary = f"Username: {extracted_fields['username']}"
    elif "favorite" in lowered or "favourite" in lowered:
        title = "User preference"
        tags.extend(["preference"])
        if extracted_fields.get("favorite_food"):
            summary = f"Favorite food: {extracted_fields['favorite_food']}"
    elif any(term in lowered for term in ("heart attack", "stroke", "allergic", "diagnosed", "surgery")):
        title = "Sensitive health fact"
        tags.extend(["health", "sensitive"])
        attributes["sensitivity"] = "high"
    elif any(term in lowered for term in ("my son", "my daughter", "my wife", "my husband", "my family", "my mom", "my mother", "my dad", "my father")):
        title = "Relationship context"
        tags.extend(["family"])
    elif any(term in lowered for term in ("don't ask", "do not ask", "stop asking", "please be", "be more", "be less")):
        title = "Interaction preference"
        tags.extend(["interaction"])

    iso_date = _extract_iso_like_date(user_text)
    if iso_date:
        attributes["event_date"] = iso_date
        tags.append("dated_fact")
    if any(term in lowered for term in _SENSITIVE_PERSONAL_TERMS):
        attributes.setdefault("sensitivity", "high")

    return LocalMemoryCaptureRequest(
        type=memory_type,
        domain=domain,
        title=title,
        summary=summary,
        content=normalized[: cfg.max_candidate_chars],
        tags=_dedupe_preserve_order(tags),
        metadata=attributes,
    )


def _normalize_personal_fact_text(user_text: str) -> str:
    return re.sub(r"\s+", " ", user_text).strip()


def _extract_personal_fact_fields(user_text: str) -> dict[str, str]:
    text = _normalize_personal_fact_text(user_text)
    lowered = text.lower()
    fields: dict[str, str] = {}

    preferred_name_match = re.search(r"\b(?:call me|you can call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text)
    if preferred_name_match:
        fields["preferred_name"] = preferred_name_match.group(1).strip()

    full_name_match = re.search(r"\bmy (?:full )?name is\s+(.+?)(?:\s+but\s+you\s+can\s+call\s+me\b|[.,;]|$)", text, re.IGNORECASE)
    if full_name_match:
        candidate_full_name = full_name_match.group(1).strip()
        if re.match(r"^[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3}$", candidate_full_name):
            fields["full_name"] = candidate_full_name
            if "preferred_name" not in fields:
                fields["preferred_name"] = fields["full_name"].split()[0]

    username_match = re.search(r"\b(?:my username is|username is)\s+([A-Za-z0-9._-]+)", text, re.IGNORECASE)
    if username_match:
        fields["username"] = username_match.group(1).strip()

    favorite_food_match = re.search(r"\bmy favou?rite food is\s+([^.,;]+)", lowered)
    if favorite_food_match:
        fields["favorite_food"] = favorite_food_match.group(1).strip()

    event_date = _extract_iso_like_date(text)
    if event_date:
        fields["event_date"] = event_date

    return fields


def _extract_iso_like_date(user_text: str) -> str | None:
    match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", user_text)
    if match:
        return match.group(0)
    month_match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(20\d{2}))?\b",
        user_text,
        re.IGNORECASE,
    )
    if not month_match:
        return None
    month_names = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    month = month_names[month_match.group(1).lower()]
    day = int(month_match.group(2))
    year = int(month_match.group(3) or 2026)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


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
