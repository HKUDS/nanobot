from typing import Optional, Union, Dict, Any

from .default_arg import DefaultArg, NotGiven
from .internal_utils import _to_dict_without_not_given


class TypeAndValue:
    primary: Union[Optional[bool], DefaultArg]
    type: Union[Optional[str], DefaultArg]
    value: Union[Optional[str], DefaultArg]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        primary: Union[Optional[bool], DefaultArg] = NotGiven,
        type: Union[Optional[str], DefaultArg] = NotGiven,
        value: Union[Optional[str], DefaultArg] = NotGiven,
        **kwargs,
    ) -> None:
        self.primary = primary
        self.type = type
        self.value = value
        self.unknown_fields = kwargs

    def to_dict(self) -> dict:
        return _to_dict_without_not_given(self)
