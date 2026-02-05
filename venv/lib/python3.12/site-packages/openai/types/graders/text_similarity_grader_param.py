# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["TextSimilarityGraderParam"]


class TextSimilarityGraderParam(TypedDict, total=False):
    """A TextSimilarityGrader object which grades text based on similarity metrics."""

    evaluation_metric: Required[
        Literal[
            "cosine",
            "fuzzy_match",
            "bleu",
            "gleu",
            "meteor",
            "rouge_1",
            "rouge_2",
            "rouge_3",
            "rouge_4",
            "rouge_5",
            "rouge_l",
        ]
    ]
    """The evaluation metric to use.

    One of `cosine`, `fuzzy_match`, `bleu`, `gleu`, `meteor`, `rouge_1`, `rouge_2`,
    `rouge_3`, `rouge_4`, `rouge_5`, or `rouge_l`.
    """

    input: Required[str]
    """The text being graded."""

    name: Required[str]
    """The name of the grader."""

    reference: Required[str]
    """The text being graded against."""

    type: Required[Literal["text_similarity"]]
    """The type of grader."""
