"""Re-rankers for memory retrieval.

This module provides two re-ranker implementations and a shared ``Reranker``
protocol:

* **CrossEncoderReranker** — uses a ``sentence-transformers`` cross-encoder
  model to re-score items.  Requires the ``sentence-transformers`` package.
* **CompositeReranker** — a lightweight, zero-dependency alternative that
  blends lexical overlap, entity overlap, BM25 pass-through, recency decay,
  and type-match signals into a composite score.

Both share the same ``rerank()`` / ``compute_rank_delta()`` interface defined
by the ``Reranker`` protocol, so callers can swap implementations via config.

The module is gated behind the rollout system:
  • ``reranker_mode = "enabled"``  – re-ranking is active
  • ``reranker_mode = "shadow"``   – both rankings are computed, delta is
    logged, but the heuristic-only ranking is returned
  • ``reranker_mode = "disabled"`` – no cross-encoder invocation (default)
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from loguru import logger

# ---------------------------------------------------------------------------
# Reranker Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Reranker(Protocol):
    """Structural interface shared by all re-ranker implementations."""

    @property
    def available(self) -> bool: ...  # pragma: no cover

    def rerank(
        self,
        query: str,
        items: list[dict[str, Any]],
        *,
        alpha: float | None = None,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover

    def compute_rank_delta(
        self,
        heuristic_order: list[str],
        reranked_order: list[str],
    ) -> float: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# CrossEncoderReranker helpers
# ---------------------------------------------------------------------------

_cross_encoder_cls: Any = None
_import_attempted = False


def _ensure_import() -> bool:
    """Try to import ``sentence_transformers.CrossEncoder`` once."""
    global _cross_encoder_cls, _import_attempted
    if _import_attempted:
        return _cross_encoder_cls is not None
    _import_attempted = True
    try:
        from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]

        _cross_encoder_cls = CrossEncoder
        return True
    except ImportError:
        logger.info("sentence-transformers not installed – cross-encoder re-ranker unavailable")
        return False


# Default lightweight model – 22 M params, works well on CPU.
DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    """Lazy-loading cross-encoder wrapper for memory result re-ranking."""

    def __init__(self, model_name: str = DEFAULT_MODEL, alpha: float = 0.5) -> None:
        self._model_name = model_name
        self._alpha = max(0.0, min(float(alpha), 1.0))
        self._model: Any = None  # lazily loaded

    @property
    def available(self) -> bool:
        """Return *True* if the underlying library is importable."""
        return _ensure_import()

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not _ensure_import():
            return None
        try:
            self._model = _cross_encoder_cls(self._model_name)
            logger.info("Loaded cross-encoder model: {}", self._model_name)
        except Exception:  # crash-barrier: third-party ML model loading
            logger.opt(exception=True).warning(
                "Failed to load cross-encoder model {}", self._model_name
            )
            self._model = None
        return self._model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        items: list[dict[str, Any]],
        *,
        alpha: float | None = None,
    ) -> list[dict[str, Any]]:
        """Re-rank *items* using cross-encoder scores blended with existing scores.

        Parameters
        ----------
        query:
            The user query used for retrieval.
        items:
            Memory items – each must have a ``"summary"`` and ``"score"`` key.
        alpha:
            Override the instance-level blending weight.  ``1.0`` means *only*
            cross-encoder; ``0.0`` means *only* heuristic.

        Returns
        -------
        The same list, re-sorted by blended score (descending).  Each item
        gets ``"ce_score"`` and ``"blended_score"`` added to its
        ``"retrieval_reason"`` dict.
        """
        if not items:
            return items

        model = self._load_model()
        if model is None:
            return items

        a = max(0.0, min(float(alpha if alpha is not None else self._alpha), 1.0))

        pairs = [(query, str(item.get("summary", ""))) for item in items]
        try:
            ce_scores: list[float] = [float(s) for s in model.predict(pairs)]
        except Exception:  # crash-barrier: third-party ML model inference
            logger.opt(exception=True).warning("Cross-encoder prediction failed")
            return items

        # Normalise CE scores to [0, 1] for blending.
        min_s = min(ce_scores) if ce_scores else 0.0
        max_s = max(ce_scores) if ce_scores else 1.0
        span = max_s - min_s
        if span < 1e-9:
            norm_scores = [0.5] * len(ce_scores)
        else:
            norm_scores = [(s - min_s) / span for s in ce_scores]

        for item, raw_ce, norm_ce in zip(items, ce_scores, norm_scores):
            heuristic = float(item.get("score", 0.0))
            blended = a * norm_ce + (1 - a) * heuristic
            item["score"] = blended

            reason = item.get("retrieval_reason")
            if not isinstance(reason, dict):
                reason = {}
                item["retrieval_reason"] = reason
            reason["ce_score"] = round(raw_ce, 4)
            reason["ce_norm"] = round(norm_ce, 4)
            reason["blended_score"] = round(blended, 4)
            reason["reranker_alpha"] = round(a, 4)

        items.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return items

    def compute_rank_delta(
        self,
        heuristic_order: list[str],
        reranked_order: list[str],
    ) -> float:
        """Return average absolute rank displacement between two orderings.

        Both lists are expected to contain item IDs in their respective order.
        Items present in only one list are ignored.
        """
        common = set(heuristic_order) & set(reranked_order)
        if not common:
            return 0.0
        h_rank = {uid: i for i, uid in enumerate(heuristic_order) if uid in common}
        r_rank = {uid: i for i, uid in enumerate(reranked_order) if uid in common}
        total = sum(abs(h_rank[uid] - r_rank[uid]) for uid in common)
        return total / len(common)


# ---------------------------------------------------------------------------
# CompositeReranker — lightweight, zero-dependency alternative
# ---------------------------------------------------------------------------

# Tunable signal weights (must sum to 1.0).
_SIGNAL_WEIGHTS: dict[str, float] = {
    "lexical": 0.30,
    "entity": 0.20,
    "bm25": 0.25,
    "recency": 0.15,
    "type_match": 0.10,
}

# Recency half-life in days for exponential decay.
_RECENCY_HALF_LIFE_DAYS: float = 30.0

# Mapping from query keywords to likely event type names.
_TYPE_KEYWORD_MAP: dict[str, str] = {
    "prefer": "preference",
    "preference": "preference",
    "like": "preference",
    "dislike": "preference",
    "decide": "decision",
    "decision": "decision",
    "learn": "lesson",
    "lesson": "lesson",
    "incident": "incident",
    "fail": "incident",
    "task": "task",
    "reflect": "reflection",
    "reflection": "reflection",
    "relationship": "relationship",
    "collaborator": "relationship",
}


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens (>=2 chars) for overlap scoring."""
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity: |intersection| / |union|."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _entity_overlap(query_tokens: set[str], entities: list[str]) -> float:
    """Fraction of query tokens found in the item's entity list."""
    if not query_tokens or not entities:
        return 0.0
    entity_tokens: set[str] = set()
    for e in entities:
        entity_tokens |= _tokenize(str(e))
    matched = len(query_tokens & entity_tokens)
    return matched / len(query_tokens)


def _recency_score(timestamp_str: str, half_life: float = _RECENCY_HALF_LIFE_DAYS) -> float:
    """Exponential decay: ``exp(-days_old / half_life)``."""
    if not timestamp_str:
        return 0.0
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        days_old = max((datetime.now(timezone.utc) - ts).total_seconds() / 86400.0, 0.0)
        return math.exp(-days_old / half_life)
    except (ValueError, TypeError):
        return 0.0


def _type_match_score(query_tokens: set[str], item_type: str) -> float:
    """Return 1.0 if item type aligns with query keywords, 0.5 otherwise."""
    item_type_lower = item_type.lower()
    for token in query_tokens:
        expected = _TYPE_KEYWORD_MAP.get(token)
        if expected and expected == item_type_lower:
            return 1.0
    return 0.5


class CompositeReranker:
    """Lightweight composite re-ranker with zero external dependencies.

    Blends five signals — lexical overlap (Jaccard), entity overlap, BM25
    pass-through, recency decay, and type match — into a single composite
    score, then α-blends with the existing heuristic score.
    """

    def __init__(self, alpha: float = 0.5) -> None:
        self._alpha = max(0.0, min(float(alpha), 1.0))

    # ------------------------------------------------------------------
    # Public API — satisfies the Reranker protocol
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Always available — no external dependencies."""
        return True

    def rerank(
        self,
        query: str,
        items: list[dict[str, Any]],
        *,
        alpha: float | None = None,
    ) -> list[dict[str, Any]]:
        """Re-rank *items* using a composite of lightweight signals.

        Parameters
        ----------
        query:
            The user query used for retrieval.
        items:
            Memory items — each should have at minimum ``"summary"`` and
            ``"score"`` keys.
        alpha:
            Override the instance-level blending weight.  ``1.0`` means *only*
            composite; ``0.0`` means *only* heuristic.

        Returns
        -------
        The same list, re-sorted by blended score (descending).  Each item
        gets ``"ce_score"`` and ``"blended_score"`` added to its
        ``"retrieval_reason"`` dict for backward compatibility.
        """
        if not items:
            return items

        a = max(0.0, min(float(alpha if alpha is not None else self._alpha), 1.0))
        query_tokens = _tokenize(query)
        w = _SIGNAL_WEIGHTS

        # Compute raw composite scores for each item.
        raw_composites: list[float] = []
        for item in items:
            summary_tokens = _tokenize(str(item.get("summary", "")))

            lexical = _jaccard(query_tokens, summary_tokens)

            entities_raw = item.get("entities", [])
            entities_list = [str(e) for e in entities_raw if isinstance(e, str)]
            entity = _entity_overlap(query_tokens, entities_list)

            reason = item.get("retrieval_reason")
            bm25 = float(reason.get("score", 0.0)) if isinstance(reason, dict) else 0.0

            recency = _recency_score(str(item.get("timestamp", "")))

            type_match = _type_match_score(query_tokens, str(item.get("type", "")))

            composite = (
                w["lexical"] * lexical
                + w["entity"] * entity
                + w["bm25"] * bm25
                + w["recency"] * recency
                + w["type_match"] * type_match
            )
            raw_composites.append(composite)

        # Normalize composite scores to [0, 1].
        min_c = min(raw_composites) if raw_composites else 0.0
        max_c = max(raw_composites) if raw_composites else 1.0
        span = max_c - min_c
        if span < 1e-9:
            norm_composites = [0.5] * len(raw_composites)
        else:
            norm_composites = [(c - min_c) / span for c in raw_composites]

        # Blend and annotate.
        for item, raw_comp, norm_comp in zip(items, raw_composites, norm_composites):
            heuristic = float(item.get("score", 0.0))
            blended = a * norm_comp + (1 - a) * heuristic
            item["score"] = blended

            reason = item.get("retrieval_reason")
            if not isinstance(reason, dict):
                reason = {}
                item["retrieval_reason"] = reason
            reason["ce_score"] = round(raw_comp, 4)
            reason["blended_score"] = round(blended, 4)
            reason["reranker_alpha"] = round(a, 4)

        items.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return items

    def compute_rank_delta(
        self,
        heuristic_order: list[str],
        reranked_order: list[str],
    ) -> float:
        """Return average absolute rank displacement between two orderings.

        Both lists are expected to contain item IDs in their respective order.
        Items present in only one list are ignored.
        """
        common = set(heuristic_order) & set(reranked_order)
        if not common:
            return 0.0
        h_rank = {uid: i for i, uid in enumerate(heuristic_order) if uid in common}
        r_rank = {uid: i for i, uid in enumerate(reranked_order) if uid in common}
        total = sum(abs(h_rank[uid] - r_rank[uid]) for uid in common)
        return total / len(common)
