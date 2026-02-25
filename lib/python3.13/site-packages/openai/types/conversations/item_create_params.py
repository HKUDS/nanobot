# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import List, Iterable
from typing_extensions import Required, TypedDict

from ..responses.response_includable import ResponseIncludable
from ..responses.response_input_item_param import ResponseInputItemParam

__all__ = ["ItemCreateParams"]


class ItemCreateParams(TypedDict, total=False):
    items: Required[Iterable[ResponseInputItemParam]]
    """The items to add to the conversation. You may add up to 20 items at a time."""

    include: List[ResponseIncludable]
    """Additional fields to include in the response.

    See the `include` parameter for
    [listing Conversation items above](https://platform.openai.com/docs/api-reference/conversations/list-items#conversations_list_items-include)
    for more information.
    """
