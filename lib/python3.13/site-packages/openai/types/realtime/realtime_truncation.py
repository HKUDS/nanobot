# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union
from typing_extensions import Literal, TypeAlias

from .realtime_truncation_retention_ratio import RealtimeTruncationRetentionRatio

__all__ = ["RealtimeTruncation"]

RealtimeTruncation: TypeAlias = Union[Literal["auto", "disabled"], RealtimeTruncationRetentionRatio]
