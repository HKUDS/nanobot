"""Adapters between nanobot dataclasses and ``mgp_client`` protocol objects.

``mgp_client`` is an *optional* dependency. This module imports it eagerly,
so it must only be imported lazily (after ``build_sidecar`` has confirmed
the package is available). See :mod:`nanobot.agent.mgp.__init__` for the
gate.
"""

from __future__ import annotations

import re
from typing import Any

from mgp_client import MemoryCandidate, PolicyContextBuilder, SearchQuery
from mgp_client.models import PolicyContext

from .models import ParsedFact, RecallIntent, RecallItem, RuntimeState


# --- policy context -------------------------------------------------------


def build_policy_context(runtime: RuntimeState, requested_action: str) -> PolicyContext:
    """Map a :class:`RuntimeState` into an MGP ``PolicyContext``.

    ``requested_action`` is one of MGP's verbs (``"search"`` / ``"write"`` /
    ``"read"`` / ...). The same runtime state is reused across recall and
    commit; only the action verb differs per call.
    """
    builder = PolicyContextBuilder(
        actor_agent=runtime.actor_agent,
        subject_kind=runtime.subject_kind,
        subject_id=runtime.user_id,
        tenant_id=runtime.tenant_id,
        task_id=runtime.session_key,
        session_id=runtime.session_key,
        task_type=f"nanobot:{runtime.channel}",
        channel=runtime.channel,
        chat_id=runtime.chat_id,
        runtime_id="nanobot",
        correlation_id=runtime.correlation_id,
    )
    return builder.build(requested_action)


# --- search query ---------------------------------------------------------


# Query-shaping patterns: strip natural-language envelopes that the agent
# might wrap a search topic in. These are conservative — agent SHOULD send a
# concise topic per the SKILL.md guidance, but we sanitize just in case.
_QUERY_ENVELOPES = (
    r"^\s*what did i say about\s+",
    r"^\s*what do you remember about\s+",
    r"^\s*do you remember\s+",
    r"^\s*what is my\s+",
    r"^\s*remind me about\s+",
    r"^\s*can you recall\s+",
    r"^\s*tell me about my\s+",
)
_QUERY_TRAIL = re.compile(r"[\?\.\!]+$")


def _normalize_query(query: str) -> str:
    """Trim conversational scaffolding so the search hits the topic itself."""
    text = re.sub(r"\s+", " ", query).strip()
    lowered = text.lower()
    for pattern in _QUERY_ENVELOPES:
        m = re.match(pattern, lowered)
        if m:
            text = text[m.end():].strip()
            break
    text = _QUERY_TRAIL.sub("", text).strip()
    return text or query.strip()


def build_search_query(runtime: RuntimeState, intent: RecallIntent) -> SearchQuery:
    """Build a typed ``SearchQuery`` payload for ``client.search_memory``."""
    normalized = _normalize_query(intent.query)
    keywords = [
        token
        for token in re.findall(r"[a-zA-Z0-9\u4e00-\u9fa5][a-zA-Z0-9_\-\u4e00-\u9fa5]*", normalized.lower())
        if len(token) > 1
    ][:8]
    intent_type = "preference_lookup" if intent.types and "preference" in intent.types else "free_text"
    return SearchQuery(
        query=normalized,
        query_text=normalized,
        intent_type=intent_type,
        keywords=keywords or None,
        subject={"kind": runtime.subject_kind, "id": runtime.user_id},
        scope=intent.scope,
        target_memory_types=intent.types,
        types=intent.types,
        top_k=intent.limit,
        limit=intent.limit,
    )


# --- write candidate ------------------------------------------------------


def build_memory_candidate(runtime: RuntimeState, fact: ParsedFact) -> MemoryCandidate:
    """Map a :class:`ParsedFact` into a typed ``MemoryCandidate``.

    A ``merge_hint`` is attached so retries — and any future near-duplicate
    suppression at the gateway — collapse onto the same canonical memory.
    """
    statement = fact.statement
    content: dict[str, Any] = {"statement": statement}
    if fact.preference_value:
        content["preference"] = fact.preference_value

    source_ref = fact.source_ref or f"nanobot:{runtime.channel}:{runtime.session_key}"
    extensions: dict[str, Any] = {
        "nanobot:channel": runtime.channel,
        "nanobot:workspace": runtime.workspace_id,
        "nanobot:session_key": runtime.session_key,
    }
    if runtime.chat_id:
        extensions["nanobot:chat_id"] = runtime.chat_id
    if runtime.correlation_id:
        extensions["nanobot:correlation_id"] = runtime.correlation_id

    dedupe_key = f"{runtime.user_id}:{fact.type}:{statement.strip().lower()}"

    return MemoryCandidate(
        candidate_kind="assertion",
        subject={"kind": runtime.subject_kind, "id": runtime.user_id},
        scope=fact.scope,
        proposed_type=fact.type,
        statement=statement,
        source={"kind": "chat", "ref": source_ref},
        content=content,
        source_evidence=[
            {"kind": "chat_message", "ref": source_ref, "excerpt": statement}
        ],
        merge_hint={"strategy": "dedupe", "dedupe_key": dedupe_key},
        extensions=extensions,
    )


# --- search response normalization ---------------------------------------


def normalize_search_results(data: dict[str, Any] | None) -> list[RecallItem]:
    """Flatten a search response payload into a uniform list of items."""
    if not data:
        return []
    items: list[RecallItem] = []
    for entry in data.get("results", []):
        items.append(
            RecallItem(
                memory=entry.get("memory") or {},
                score=entry.get("score"),
                score_kind=entry.get("score_kind"),
                retrieval_mode=entry.get("retrieval_mode"),
                return_mode=entry.get("return_mode") or "raw",
                redaction_info=entry.get("redaction_info"),
                backend_origin=entry.get("backend_origin"),
                consumable_text=entry.get("consumable_text"),
                matched_terms=entry.get("matched_terms"),
                explanation=entry.get("explanation"),
            )
        )
    return items
