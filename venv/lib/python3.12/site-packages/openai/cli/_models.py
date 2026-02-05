from typing import Any
from typing_extensions import ClassVar

import pydantic

from .. import _models
from .._compat import PYDANTIC_V1, ConfigDict


class BaseModel(_models.BaseModel):
    if PYDANTIC_V1:

        class Config(pydantic.BaseConfig):  # type: ignore
            extra: Any = pydantic.Extra.ignore  # type: ignore
            arbitrary_types_allowed: bool = True
    else:
        model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", arbitrary_types_allowed=True)
