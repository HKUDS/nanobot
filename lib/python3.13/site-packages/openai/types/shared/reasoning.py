# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .reasoning_effort import ReasoningEffort

__all__ = ["Reasoning"]


class Reasoning(BaseModel):
    """**gpt-5 and o-series models only**

    Configuration options for
    [reasoning models](https://platform.openai.com/docs/guides/reasoning).
    """

    effort: Optional[ReasoningEffort] = None
    """
    Constrains effort on reasoning for
    [reasoning models](https://platform.openai.com/docs/guides/reasoning). Currently
    supported values are `none`, `minimal`, `low`, `medium`, `high`, and `xhigh`.
    Reducing reasoning effort can result in faster responses and fewer tokens used
    on reasoning in a response.

    - `gpt-5.1` defaults to `none`, which does not perform reasoning. The supported
      reasoning values for `gpt-5.1` are `none`, `low`, `medium`, and `high`. Tool
      calls are supported for all reasoning values in gpt-5.1.
    - All models before `gpt-5.1` default to `medium` reasoning effort, and do not
      support `none`.
    - The `gpt-5-pro` model defaults to (and only supports) `high` reasoning effort.
    - `xhigh` is supported for all models after `gpt-5.1-codex-max`.
    """

    generate_summary: Optional[Literal["auto", "concise", "detailed"]] = None
    """**Deprecated:** use `summary` instead.

    A summary of the reasoning performed by the model. This can be useful for
    debugging and understanding the model's reasoning process. One of `auto`,
    `concise`, or `detailed`.
    """

    summary: Optional[Literal["auto", "concise", "detailed"]] = None
    """A summary of the reasoning performed by the model.

    This can be useful for debugging and understanding the model's reasoning
    process. One of `auto`, `concise`, or `detailed`.

    `concise` is supported for `computer-use-preview` models and all reasoning
    models after `gpt-5`.
    """
