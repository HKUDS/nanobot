"""LLM-based skill selection for progressive skill loading (modes A/B)."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.config.schema import SkillRetrievalConfig
from nanobot.providers.base import LLMProvider
from nanobot.utils.prompt_templates import render_template

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    """Minimal skill metadata sent to the selector model."""

    name: str
    description: str


def parse_skill_selection_response(
    content: str | None,
    *,
    allowed: set[str],
    max_k: int,
) -> list[str]:
    """Parse ``{"skills": [...]}`` from model output; ignore unknown names."""
    if not content or max_k <= 0:
        return []

    text = _JSON_FENCE_RE.sub("", content.strip()).strip()
    data: object
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if not match:
            return []
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return []

    names: object
    if isinstance(data, dict):
        names = data.get("skills", data.get("skill", []))
    elif isinstance(data, list):
        names = data
    else:
        return []

    if not isinstance(names, list):
        return []

    selected: list[str] = []
    for item in names:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name not in allowed or name in selected:
            continue
        selected.append(name)
        if len(selected) >= max_k:
            break
    return selected


def order_selected_candidates(
    candidates: Sequence[SkillCandidate],
    selected_names: Sequence[str],
    *,
    max_k: int,
) -> list[str]:
    """Keep candidate list order; do not rerank by model output order."""
    selected = set(selected_names)
    ordered = [candidate.name for candidate in candidates if candidate.name in selected]
    return ordered[:max_k]


class SkillLLMSelector:
    """Ask a small/fast model to pick relevant skills from a candidate set."""

    def __init__(self, provider: LLMProvider, config: SkillRetrievalConfig) -> None:
        self._provider = provider
        self._config = config
        self._lock = threading.RLock()
        self._cache: OrderedDict[tuple[Any, ...], list[str]] = OrderedDict()

    async def select(
        self,
        query: str,
        candidates: Sequence[SkillCandidate],
        *,
        k: int,
    ) -> list[str]:
        """Return up to *k* skill names chosen by the LLM."""
        normalized = " ".join(query.split()).strip().lower()
        if not normalized or not candidates or k <= 0:
            return []

        allowed = {candidate.name for candidate in candidates}
        cache_key = (normalized, tuple(candidate.name for candidate in candidates), k)
        cache_size = self._config.query_cache_size

        with self._lock:
            if cache_size > 0 and cache_key in self._cache:
                cached = list(self._cache[cache_key])
                logger.info(
                    "Skill LLM select [cache hit]: query={!r} k={} candidates={} -> {}",
                    query,
                    k,
                    [candidate.name for candidate in candidates],
                    cached,
                )
                self._cache.move_to_end(cache_key)
                return cached

        logger.info(
            "Skill LLM select [start]: query={!r} k={} model={} timeout={}s candidates={}",
            query,
            k,
            self._config.llm_model,
            self._config.llm_timeout_s,
            [(candidate.name, candidate.description) for candidate in candidates],
        )
        prompt_candidates = "\n".join(
            f"- {candidate.name}: {candidate.description or candidate.name}"
            for candidate in candidates
        )
        user_prompt = render_template(
            "agent/skill_select.md",
            query=query.strip(),
            candidates=prompt_candidates,
            max_k=k,
        )
        messages = [
            {
                "role": "system",
                "content": "You are a skill router. Output valid JSON only.",
            },
            {"role": "user", "content": user_prompt},
        ]
        logger.debug("Skill LLM select prompt:\n{}", user_prompt)

        try:
            async with asyncio.timeout(self._config.llm_timeout_s):
                response = await self._provider.chat_with_retry(
                    messages=messages,
                    model=self._config.llm_model,
                    max_tokens=self._config.llm_max_tokens,
                    temperature=0,
                    retry_mode="standard",
                )
        except TimeoutError:
            logger.warning("Skill LLM selection timed out after {}s", self._config.llm_timeout_s)
            return []
        except Exception as exc:
            logger.warning("Skill LLM selection failed: {}", exc)
            return []

        if response.finish_reason == "error":
            logger.warning("Skill LLM selection provider error: {}", response.content)
            return []

        raw_content = response.content or ""
        logger.info(
            "Skill LLM select [response]: finish_reason={} content={!r}",
            response.finish_reason,
            raw_content[:500],
        )

        selected = parse_skill_selection_response(
            response.content,
            allowed=allowed,
            max_k=k,
        )
        ordered = order_selected_candidates(candidates, selected, max_k=k)
        logger.info(
            "Skill LLM select [done]: parsed={} ordered={}",
            selected,
            ordered,
        )

        with self._lock:
            if cache_size > 0:
                self._cache[cache_key] = list(ordered)
                self._cache.move_to_end(cache_key)
                while len(self._cache) > cache_size:
                    self._cache.popitem(last=False)

        return ordered


def resolve_skill_retrieval_provider(
    config: Any,
    skill_retrieval: SkillRetrievalConfig,
    fallback_provider: LLMProvider,
) -> LLMProvider | None:
    """Create the LLM provider used for skill selection, if needed."""
    if not skill_retrieval.enable or skill_retrieval.mode == "fts":
        return None

    if skill_retrieval.llm_model:
        from nanobot.providers.factory import make_provider

        try:
            return make_provider(config, model=skill_retrieval.llm_model)
        except Exception as exc:
            logger.warning(
                "Failed to create skill retrieval model {!r}: {}; using main agent provider",
                skill_retrieval.llm_model,
                exc,
            )
    return fallback_provider
