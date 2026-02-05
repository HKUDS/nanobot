# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["InputTokenCountResponse"]


class InputTokenCountResponse(BaseModel):
    input_tokens: int

    object: Literal["response.input_tokens"]
