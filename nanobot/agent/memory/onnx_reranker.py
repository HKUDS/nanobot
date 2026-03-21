"""ONNX Runtime cross-encoder for high-quality memory re-ranking.

Uses ms-marco-MiniLM-L-6-v2 exported to ONNX format for inference
without PyTorch. Model is downloaded on first use from HuggingFace Hub.

Activated by config: reranker_model = "onnx:ms-marco-MiniLM-L-6-v2"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from loguru import logger
from tokenizers import Tokenizer

_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_CACHE_DIR = Path.home() / ".cache" / "nanobot" / "models"
_HF_BASE = "https://huggingface.co"


class OnnxCrossEncoderReranker:
    """ONNX-based cross-encoder reranker using ms-marco-MiniLM-L-6-v2.

    Downloads the ONNX model and HuggingFace tokenizer on first use,
    caching them under ``~/.cache/nanobot/models/<model_name>/``.
    Conforms to the :class:`Reranker` protocol defined in ``reranker.py``.
    """

    def __init__(self, model_name: str = "ms-marco-MiniLM-L-6-v2", alpha: float = 0.5) -> None:
        self._model_name = model_name
        self._alpha = max(0.0, min(1.0, float(alpha)))
        self._session: ort.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None
        self._model_dir = _CACHE_DIR / model_name

    # ------------------------------------------------------------------
    # Reranker protocol — property
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Always *True* — onnxruntime is a mandatory dependency."""
        return True

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def _ensure_model(self) -> bool:
        """Load model and tokenizer, downloading if necessary. Returns *True* on success."""
        if self._session is not None:
            return True

        model_path = self._model_dir / "model.onnx"
        tokenizer_path = self._model_dir / "tokenizer.json"

        if not model_path.exists() or not tokenizer_path.exists():
            if not self._download_model():
                return False

        try:
            self._session = ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
            self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
            return True
        except Exception as exc:  # crash-barrier: third-party model loading
            logger.warning("Failed to load ONNX model: {}", exc)
            return False

    def _download_model(self) -> bool:
        """Download ``model.onnx`` and ``tokenizer.json`` from HuggingFace Hub."""
        import httpx

        self._model_dir.mkdir(parents=True, exist_ok=True)
        repo = f"{_HF_BASE}/{_DEFAULT_MODEL}/resolve/main"

        files: dict[str, Path] = {
            "onnx/model.onnx": self._model_dir / "model.onnx",
            "tokenizer.json": self._model_dir / "tokenizer.json",
        }

        for remote_path, local_path in files.items():
            if local_path.exists():
                continue
            url = f"{repo}/{remote_path}"
            logger.info("Downloading {} -> {}", url, local_path)
            try:
                with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
                    resp.raise_for_status()
                    with open(local_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            f.write(chunk)
            except Exception as exc:  # crash-barrier: network download
                logger.error("Failed to download {}: {}", url, exc)
                local_path.unlink(missing_ok=True)
                return False
        return True

    # ------------------------------------------------------------------
    # Public API — satisfies the Reranker protocol
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        items: list[dict[str, Any]],
        *,
        alpha: float | None = None,
    ) -> list[dict[str, Any]]:
        """Re-rank *items* using ONNX cross-encoder scores blended with heuristic scores.

        Parameters
        ----------
        query:
            The user query used for retrieval.
        items:
            Memory items -- each must have a ``"summary"`` key.
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

        if not self._ensure_model():
            return items  # graceful degradation

        assert self._tokenizer is not None  # guaranteed by _ensure_model
        assert self._session is not None

        effective_alpha = max(0.0, min(float(alpha if alpha is not None else self._alpha), 1.0))

        # Tokenize query-summary pairs
        pairs = [(query, str(item.get("summary", ""))) for item in items]
        encodings = [self._tokenizer.encode(q, s) for q, s in pairs]

        max_len = min(max(len(e.ids) for e in encodings), 512)
        batch_size = len(encodings)

        input_ids = np.zeros((batch_size, max_len), dtype=np.int64)
        attention_mask = np.zeros((batch_size, max_len), dtype=np.int64)
        token_type_ids = np.zeros((batch_size, max_len), dtype=np.int64)

        for i, enc in enumerate(encodings):
            length = min(len(enc.ids), max_len)
            input_ids[i, :length] = enc.ids[:length]
            attention_mask[i, :length] = enc.attention_mask[:length]
            token_type_ids[i, :length] = enc.type_ids[:length]

        try:
            outputs = self._session.run(
                None,
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "token_type_ids": token_type_ids,
                },
            )
            logits = outputs[0]  # shape: (batch, 1) or (batch,)
            scores = logits.flatten()
        except Exception as exc:  # crash-barrier: ONNX inference
            logger.warning("ONNX inference failed: {}", exc)
            return items

        # Normalize to [0, 1] via sigmoid
        ce_scores = 1.0 / (1.0 + np.exp(-scores))

        # Blend with heuristic scores
        for i, item in enumerate(items):
            ce_score = float(ce_scores[i])
            heuristic = float(item.get("score", 0.0))
            blended = effective_alpha * ce_score + (1 - effective_alpha) * heuristic
            item["score"] = blended

            reason = item.get("retrieval_reason")
            if not isinstance(reason, dict):
                reason = {}
                item["retrieval_reason"] = reason
            reason["ce_score"] = round(ce_score, 4)
            reason["blended_score"] = round(blended, 4)
            reason["reranker_alpha"] = round(effective_alpha, 4)

        # Sort by blended score descending
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
