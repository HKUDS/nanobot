# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Dict
from typing_extensions import Literal

from pydantic import Field as FieldInfo

from .._models import BaseModel

__all__ = ["EvalCustomDataSourceConfig"]


class EvalCustomDataSourceConfig(BaseModel):
    """
    A CustomDataSourceConfig which specifies the schema of your `item` and optionally `sample` namespaces.
    The response schema defines the shape of the data that will be:
    - Used to define your testing criteria and
    - What data is required when creating a run
    """

    schema_: Dict[str, object] = FieldInfo(alias="schema")
    """
    The json schema for the run data source items. Learn how to build JSON schemas
    [here](https://json-schema.org/).
    """

    type: Literal["custom"]
    """The type of data source. Always `custom`."""
