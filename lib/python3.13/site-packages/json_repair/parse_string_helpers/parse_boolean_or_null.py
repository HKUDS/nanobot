from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..json_parser import JSONParser  # noqa: TID252


def parse_boolean_or_null(parser: "JSONParser") -> bool | str | None:
    # <boolean> is one of the literal strings 'true', 'false', or 'null' (unquoted)
    char = (parser.get_char_at() or "").lower()
    value_map: dict[str, tuple[str, bool | None]] = {
        "t": ("true", True),
        "f": ("false", False),
        "n": ("null", None),
    }
    value: tuple[str, bool | None] = value_map[char]

    i = 0
    starting_index = parser.index
    while char and i < len(value[0]) and char == value[0][i]:
        i += 1
        parser.index += 1
        char = (parser.get_char_at() or "").lower()
    if i == len(value[0]):
        return value[1]

    # If nothing works reset the index before returning
    parser.index = starting_index
    return ""
