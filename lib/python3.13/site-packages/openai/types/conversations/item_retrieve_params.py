# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import List
from typing_extensions import Required, TypedDict

from ..responses.response_includable import ResponseIncludable

__all__ = ["ItemRetrieveParams"]


class ItemRetrieveParams(TypedDict, total=False):
    conversation_id: Required[str]

    include: List[ResponseIncludable]
    """Additional fields to include in the response.

    See the `include` parameter for
    [listing Conversation items above](https://platform.openai.com/docs/api-reference/conversations/list-items#conversations_list_items-include)
    for more information.
    """
