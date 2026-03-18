"""Optional cross-encoder re-ranker for memory retrieval.

When ``sentence-transformers`` is installed, a lightweight CrossEncoder model
(default: ``cross-encoder/ms-marco-MiniLM-L-6-v2``, 22 M params, CPU-friendly)
re-scores retrieved memory items against the user query.  The final score is an
α-blend of the cross-encoder relevance and the existing heuristic score:

    blended = α * ce_score + (1 − α) * heuristic_score

The module is gated behind the rollout system:
  • ``reranker_mode = "enabled"``  – re-ranking is active
  • ``reranker_mode = "shadow"``   – both rankings are computed, delta is
    logged, but the heuristic-only ranking is returned
  • ``reranker_mode = "disabled"`` – no cross-encoder invocation (default)
"""

from __future__ import annotations

from typing import Any

from loguru import logger

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
