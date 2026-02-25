from typing import Any


class MissingValueType:
    def __repr__(self) -> str:
        return "<MISSING_VALUE>"

    def __deepcopy__(self, memo: dict[int, Any]) -> "MissingValueType":
        return self


MISSING_VALUE = MissingValueType()

JSONReturnType = dict[str, Any] | list[Any] | str | float | int | bool | None
STRING_DELIMITERS: list[str] = ['"', "'", "“", "”"]
