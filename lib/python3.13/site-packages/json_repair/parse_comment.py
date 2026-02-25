from typing import TYPE_CHECKING

from .utils.constants import JSONReturnType
from .utils.json_context import ContextValues

if TYPE_CHECKING:
    from .json_parser import JSONParser


def parse_comment(self: "JSONParser") -> JSONReturnType:
    """
    Parse code-like comments:

    - "# comment": A line comment that continues until a newline.
    - "// comment": A line comment that continues until a newline.
    - "/* comment */": A block comment that continues until the closing delimiter "*/".

    The comment is skipped over and an empty string is returned so that comments do not interfere
    with the actual JSON elements.
    """
    char = self.get_char_at()
    termination_characters = ["\n", "\r"]
    if ContextValues.ARRAY in self.context.context:
        termination_characters.append("]")
    if ContextValues.OBJECT_VALUE in self.context.context:
        termination_characters.append("}")
    if ContextValues.OBJECT_KEY in self.context.context:
        termination_characters.append(":")
    # Line comment starting with #
    if char == "#":
        comment = ""
        while char and char not in termination_characters:
            comment += char
            self.index += 1
            char = self.get_char_at()
        self.log(f"Found line comment: {comment}, ignoring")
    # Comments starting with '/'
    elif char == "/":
        next_char = self.get_char_at(1)
        # Handle line comment starting with //
        if next_char == "/":
            comment = "//"
            self.index += 2  # Skip both slashes.
            char = self.get_char_at()
            while char and char not in termination_characters:
                comment += char
                self.index += 1
                char = self.get_char_at()
            self.log(f"Found line comment: {comment}, ignoring")
        # Handle block comment starting with /*
        elif next_char == "*":
            comment = "/*"
            self.index += 2  # Skip '/*'
            while True:
                char = self.get_char_at()
                if not char:
                    self.log("Reached end-of-string while parsing block comment; unclosed block comment.")
                    break
                comment += char
                self.index += 1
                if comment.endswith("*/"):
                    break
            self.log(f"Found block comment: {comment}, ignoring")
        else:
            # Skip standalone '/' characters that are not part of a comment
            # to avoid getting stuck in an infinite loop
            self.index += 1
    if self.context.empty:
        return self.parse_json()
    return ""
