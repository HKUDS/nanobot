# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import Literal, TypeAlias

from .realtime_truncation_retention_ratio_param import RealtimeTruncationRetentionRatioParam

__all__ = ["RealtimeTruncationParam"]

RealtimeTruncationParam: TypeAlias = Union[Literal["auto", "disabled"], RealtimeTruncationRetentionRatioParam]
