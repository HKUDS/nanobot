from typing import TYPE_CHECKING

from .parse_string_helpers.parse_boolean_or_null import parse_boolean_or_null
from .parse_string_helpers.parse_json_llm_block import parse_json_llm_block
from .utils.constants import STRING_DELIMITERS, JSONReturnType
from .utils.json_context import ContextValues

if TYPE_CHECKING:
    from .json_parser import JSONParser


def parse_string(self: "JSONParser") -> JSONReturnType:
    # Utility function to append a character to the accumulator and update the index
    def _append_literal_char(acc: str, current_char: str) -> tuple[str, str | None]:
        acc += current_char
        self.index += 1
        char = self.get_char_at()
        return acc, char

    # <string> is a string of valid characters enclosed in quotes
    # i.e. { name: "John" }
    # Somehow all weird cases in an invalid JSON happen to be resolved in this function, so be careful here

    # Flag to manage corner cases related to missing starting quote
    missing_quotes = False
    doubled_quotes = False
    lstring_delimiter = rstring_delimiter = '"'

    char = self.get_char_at()
    if char in ["#", "/"]:
        return self.parse_comment()
    # A valid string can only start with a valid quote or, in our case, with a literal
    while char and char not in STRING_DELIMITERS and not char.isalnum():
        self.index += 1
        char = self.get_char_at()

    if not char:
        # This is an empty string
        return ""

    # Ensuring we use the right delimiter
    if char == "'":
        lstring_delimiter = rstring_delimiter = "'"
    elif char == "“":
        lstring_delimiter = "“"
        rstring_delimiter = "”"
    elif char.isalnum():
        # This could be a <boolean> and not a string. Because (T)rue or (F)alse or (N)ull are valid
        # But remember, object keys are only of type string
        if char.lower() in ["t", "f", "n"] and self.context.current != ContextValues.OBJECT_KEY:
            value = parse_boolean_or_null(self)
            if value != "":
                return value
        self.log(
            "While parsing a string, we found a literal instead of a quote",
        )
        missing_quotes = True

    if not missing_quotes:
        self.index += 1
    if self.get_char_at() == "`":
        ret_val = parse_json_llm_block(self)
        # If we found a valid JSON block, return it, otherwise continue parsing the string
        if ret_val is not False:
            return ret_val
        self.log(
            "While parsing a string, we found code fences but they did not enclose valid JSON, continuing parsing the string",
        )
    # There is sometimes a weird case of doubled quotes, we manage this also later in the while loop
    if self.get_char_at() == lstring_delimiter:
        # If it's an empty key, this was easy
        if (
            (self.context.current == ContextValues.OBJECT_KEY and self.get_char_at(1) == ":")
            or (self.context.current == ContextValues.OBJECT_VALUE and self.get_char_at(1) in [",", "}"])
            or (self.context.current == ContextValues.ARRAY and self.get_char_at(1) in [",", "]"])
        ):
            self.index += 1
            return ""
        if self.get_char_at(1) == lstring_delimiter:
            # There's something fishy about this, we found doubled quotes and then again quotes
            self.log(
                "While parsing a string, we found a doubled quote and then a quote again, ignoring it",
            )
            if self.strict:
                raise ValueError("Found doubled quotes followed by another quote.")
            return ""
        # Find the next delimiter
        i = self.skip_to_character(character=rstring_delimiter, idx=1)
        next_c = self.get_char_at(i)
        # Now check that the next character is also a delimiter to ensure that we have "".....""
        # In that case we ignore this rstring delimiter
        if self.get_char_at(i + 1) == rstring_delimiter:
            self.log(
                "While parsing a string, we found a valid starting doubled quote",
            )
            doubled_quotes = True
            self.index += 1
        else:
            # Ok this is not a doubled quote, check if this is an empty string or not
            i = self.scroll_whitespaces(idx=1)
            next_c = self.get_char_at(i)
            if next_c in STRING_DELIMITERS + ["{", "["]:
                # something fishy is going on here
                self.log(
                    "While parsing a string, we found a doubled quote but also another quote afterwards, ignoring it",
                )
                if self.strict:
                    raise ValueError(
                        "Found doubled quotes followed by another quote while parsing a string.",
                    )
                self.index += 1
                return ""
            if next_c not in [",", "]", "}"]:
                self.log(
                    "While parsing a string, we found a doubled quote but it was a mistake, removing one quote",
                )
                self.index += 1

    # Initialize our return value
    string_acc = ""

    # Here things get a bit hairy because a string missing the final quote can also be a key or a value in an object
    # In that case we need to use the ":|,|}" characters as terminators of the string
    # So this will stop if:
    # * It finds a closing quote
    # * It iterated over the entire sequence
    # * If we are fixing missing quotes in an object, when it finds the special terminators
    char = self.get_char_at()
    unmatched_delimiter = False
    while char and char != rstring_delimiter:
        if missing_quotes:
            if self.context.current == ContextValues.OBJECT_KEY and (char == ":" or char.isspace()):
                self.log(
                    "While parsing a string missing the left delimiter in object key context, we found a :, stopping here",
                )
                break
            if self.context.current == ContextValues.ARRAY and char in ["]", ","]:
                self.log(
                    "While parsing a string missing the left delimiter in array context, we found a ] or ,, stopping here",
                )
                break
        if (
            not self.stream_stable
            and self.context.current == ContextValues.OBJECT_VALUE
            and char
            in [
                ",",
                "}",
            ]
            and (not string_acc or string_acc[-1] != rstring_delimiter)
        ):
            rstring_delimiter_missing = True
            # check if this is a case in which the closing comma is NOT missing instead
            self.skip_whitespaces()
            if self.get_char_at(1) == "\\":
                # Ok this is a quoted string, skip
                rstring_delimiter_missing = False
            i = self.skip_to_character(character=rstring_delimiter, idx=1)
            next_c = self.get_char_at(i)
            if next_c:
                i += 1
                # found a delimiter, now we need to check that is followed strictly by a comma or brace
                # or the string ended
                i = self.scroll_whitespaces(idx=i)
                next_c = self.get_char_at(i)
                if not next_c or next_c in [",", "}"]:
                    rstring_delimiter_missing = False
                else:
                    # OK but this could still be some garbage at the end of the string
                    # So we need to check if we find a new lstring_delimiter afterwards
                    # If we do, maybe this is a missing delimiter
                    i = self.skip_to_character(character=lstring_delimiter, idx=i)
                    next_c = self.get_char_at(i)
                    if not next_c:
                        rstring_delimiter_missing = False
                    else:
                        # But again, this could just be something a bit stupid like "lorem, "ipsum" sic"
                        # Check if we find a : afterwards (skipping space)
                        i = self.scroll_whitespaces(idx=i + 1)
                        next_c = self.get_char_at(i)
                        if next_c and next_c != ":":
                            rstring_delimiter_missing = False
            else:
                # There could be a case in which even the next key:value is missing delimeters
                # because it might be a systemic issue with the output
                # So let's check if we can find a : in the string instead
                i = self.skip_to_character(character=":", idx=1)
                next_c = self.get_char_at(i)
                if next_c:
                    # OK then this is a systemic issue with the output
                    break
                # skip any whitespace first
                i = self.scroll_whitespaces(idx=1)
                # We couldn't find any rstring_delimeter before the end of the string
                # check if this is the last string of an object and therefore we can keep going
                # make an exception if this is the last char before the closing brace
                j = self.skip_to_character(character="}", idx=i)
                if j - i > 1:
                    # Ok it's not right after the comma
                    # Let's ignore
                    rstring_delimiter_missing = False
                # Check that j was not out of bound
                elif self.get_char_at(j):
                    # Check for an unmatched opening brace in string_acc
                    for c in reversed(string_acc):
                        if c == "{":
                            # Ok then this is part of the string
                            rstring_delimiter_missing = False
                            break
            if rstring_delimiter_missing:
                self.log(
                    "While parsing a string missing the left delimiter in object value context, we found a , or } and we couldn't determine that a right delimiter was present. Stopping here",
                )
                break
        if (
            not self.stream_stable
            and char == "]"
            and ContextValues.ARRAY in self.context.context
            and (not string_acc or string_acc[-1] != rstring_delimiter)
        ):
            # We found the end of an array and we are in array context
            # So let's check if we find a rstring_delimiter forward otherwise end early
            i = self.skip_to_character(rstring_delimiter)
            if not self.get_char_at(i):
                # No delimiter found
                break
        if self.context.current == ContextValues.OBJECT_VALUE and char == "}":
            # We found the end of an object while parsing a value
            # Check if the object is really over, to avoid doubling the closing brace
            i = self.scroll_whitespaces(idx=1)
            next_c = self.get_char_at(i)
            if next_c == "`" and self.get_char_at(i + 1) == "`" and self.get_char_at(i + 2) == "`":
                # This could be a special case in which the LLM added code fences after the object
                # So we need to check if there are another two ` after this one`
                self.log(
                    "While parsing a string in object value context, we found a } that closes the object before code fences, stopping here",
                )
                break
            if not next_c:
                self.log(
                    "While parsing a string in object value context, we found a } that closes the object, stopping here",
                )
                break
        string_acc += char
        self.index += 1
        char = self.get_char_at()
        if char is None:
            # Unclosed string ends with a \ character. This character is ignored if stream_stable = True.
            if self.stream_stable and string_acc and string_acc[-1] == "\\":
                string_acc = string_acc[:-1]
            break
        if string_acc and string_acc[-1] == "\\":
            # This is a special case, if people use real strings this might happen
            self.log("Found a stray escape sequence, normalizing it")
            if char in [rstring_delimiter, "t", "n", "r", "b", "\\"]:
                string_acc = string_acc[:-1]
                escape_seqs = {"t": "\t", "n": "\n", "r": "\r", "b": "\b"}
                string_acc += escape_seqs.get(char, char)
                self.index += 1
                char = self.get_char_at()
                while char and string_acc and string_acc[-1] == "\\" and char in [rstring_delimiter, "\\"]:
                    # this is a bit of a special case, if I don't do this it will close the loop or create a train of \\
                    # I don't love it though
                    string_acc = string_acc[:-1] + char
                    self.index += 1
                    char = self.get_char_at()
                continue
            if char in ["u", "x"]:
                # If we find a unicode escape sequence, normalize it
                num_chars = 4 if char == "u" else 2
                next_chars = self.json_str[self.index + 1 : self.index + 1 + num_chars]
                if len(next_chars) == num_chars and all(c in "0123456789abcdefABCDEF" for c in next_chars):
                    self.log("Found a unicode escape sequence, normalizing it")
                    string_acc = string_acc[:-1] + chr(int(next_chars, 16))
                    self.index += 1 + num_chars
                    char = self.get_char_at()
                    continue
            elif char in STRING_DELIMITERS and char != rstring_delimiter:
                self.log("Found a delimiter that was escaped but shouldn't be escaped, removing the escape")
                string_acc = string_acc[:-1] + char
                self.index += 1
                char = self.get_char_at()
                continue
        # If we are in object key context and we find a colon, it could be a missing right quote
        if char == ":" and not missing_quotes and self.context.current == ContextValues.OBJECT_KEY:
            # Ok now we need to check if this is followed by a value like "..."
            i = self.skip_to_character(character=lstring_delimiter, idx=1)
            next_c = self.get_char_at(i)
            if next_c:
                i += 1
                # found the first delimiter
                i = self.skip_to_character(character=rstring_delimiter, idx=i)
                next_c = self.get_char_at(i)
                if next_c:
                    # found a second delimiter
                    i += 1
                    # Skip spaces
                    i = self.scroll_whitespaces(idx=i)
                    ch = self.get_char_at(i)
                    if ch in [",", "}"]:
                        # Ok then this is a missing right quote
                        self.log(
                            f"While parsing a string missing the right delimiter in object key context, we found a {ch} stopping here",
                        )
                        break
            else:
                # The string ended without finding a lstring_delimiter, I will assume this is a missing right quote
                self.log(
                    "While parsing a string missing the right delimiter in object key context, we found a :, stopping here",
                )
                break
        # ChatGPT sometimes forget to quote stuff in html tags or markdown, so we do this whole thing here
        if char == rstring_delimiter and string_acc and string_acc[-1] != "\\":
            # Special case here, in case of double quotes one after another
            if doubled_quotes and self.get_char_at(1) == rstring_delimiter:
                self.log("While parsing a string, we found a doubled quote, ignoring it")
                self.index += 1
            elif missing_quotes and self.context.current == ContextValues.OBJECT_VALUE:
                # In case of missing starting quote I need to check if the delimeter is the end or the beginning of a key
                i = 1
                next_c = self.get_char_at(i)
                while next_c and next_c not in [
                    rstring_delimiter,
                    lstring_delimiter,
                ]:
                    i += 1
                    next_c = self.get_char_at(i)
                if next_c:
                    # We found a quote, now let's make sure there's a ":" following
                    i += 1
                    # found a delimiter, now we need to check that is followed strictly by a comma or brace
                    i = self.scroll_whitespaces(idx=i)
                    if self.get_char_at(i) == ":":
                        # Reset the cursor
                        self.index -= 1
                        char = self.get_char_at()
                        self.log(
                            "In a string with missing quotes and object value context, I found a delimeter but it turns out it was the beginning on the next key. Stopping here.",
                        )
                        break
            elif unmatched_delimiter:
                unmatched_delimiter = False
                string_acc, char = _append_literal_char(string_acc, char)
            else:
                # Check if eventually there is a rstring delimiter, otherwise we bail
                i = 1
                next_c = self.get_char_at(i)
                check_comma_in_object_value = True
                while next_c and next_c not in [
                    rstring_delimiter,
                    lstring_delimiter,
                ]:
                    # This is a bit of a weird workaround, essentially in object_value context we don't always break on commas
                    # This is because the routine after will make sure to correct any bad guess and this solves a corner case
                    if check_comma_in_object_value and next_c.isalpha():
                        check_comma_in_object_value = False
                    # If we are in an object context, let's check for the right delimiters
                    if (
                        (ContextValues.OBJECT_KEY in self.context.context and next_c in [":", "}"])
                        or (ContextValues.OBJECT_VALUE in self.context.context and next_c == "}")
                        or (ContextValues.ARRAY in self.context.context and next_c in ["]", ","])
                        or (
                            check_comma_in_object_value
                            and self.context.current == ContextValues.OBJECT_VALUE
                            and next_c == ","
                        )
                    ):
                        break
                    i += 1
                    next_c = self.get_char_at(i)
                # If we stopped for a comma in object_value context, let's check if find a "} at the end of the string
                if next_c == "," and self.context.current == ContextValues.OBJECT_VALUE:
                    i += 1
                    i = self.skip_to_character(character=rstring_delimiter, idx=i)
                    next_c = self.get_char_at(i)
                    # Ok now I found a delimiter, let's skip whitespaces and see if next we find a } or a ,
                    i += 1
                    i = self.scroll_whitespaces(idx=i)
                    next_c = self.get_char_at(i)
                    if next_c in ["}", ","]:
                        self.log(
                            "While parsing a string, we found a misplaced quote that would have closed the string but has a different meaning here, ignoring it",
                        )
                        string_acc, char = _append_literal_char(string_acc, char)
                        continue
                elif next_c == rstring_delimiter and self.get_char_at(i - 1) != "\\":
                    # Check if self.index:self.index+i is only whitespaces, break if that's the case
                    if _only_whitespace_until(self, i):
                        break
                    if self.context.current == ContextValues.OBJECT_VALUE:
                        i = self.scroll_whitespaces(idx=i + 1)
                        if self.get_char_at(i) == ",":
                            # So we found a comma, this could be a case of a single quote like "va"lue",
                            # Search if it's followed by another key, starting with the first delimeter
                            i = self.skip_to_character(character=lstring_delimiter, idx=i + 1)
                            i += 1
                            i = self.skip_to_character(character=rstring_delimiter, idx=i + 1)
                            i += 1
                            i = self.scroll_whitespaces(idx=i)
                            next_c = self.get_char_at(i)
                            if next_c == ":":
                                self.log(
                                    "While parsing a string, we found a misplaced quote that would have closed the string but has a different meaning here, ignoring it",
                                )
                                string_acc, char = _append_literal_char(string_acc, char)
                                continue
                        # We found a delimiter and we need to check if this is a key
                        # so find a rstring_delimiter and a colon after
                        i = self.skip_to_character(character=rstring_delimiter, idx=i + 1)
                        i += 1
                        next_c = self.get_char_at(i)
                        while next_c and next_c != ":":
                            if next_c in [",", "]", "}"] or (
                                next_c == rstring_delimiter and self.get_char_at(i - 1) != "\\"
                            ):
                                break
                            i += 1
                            next_c = self.get_char_at(i)
                        # Only if we fail to find a ':' then we know this is misplaced quote
                        if next_c != ":":
                            self.log(
                                "While parsing a string, we found a misplaced quote that would have closed the string but has a different meaning here, ignoring it",
                            )
                            unmatched_delimiter = not unmatched_delimiter
                            string_acc, char = _append_literal_char(string_acc, char)
                    elif self.context.current == ContextValues.ARRAY:
                        # So here we can have a few valid cases:
                        # ["bla bla bla "puppy" bla bla bla "kitty" bla bla"]
                        # ["value1" value2", "value3"]
                        # The basic idea is that if we find an even number of delimiters after this delimiter
                        # we ignore this delimiter as it should be fine
                        even_delimiters = next_c == rstring_delimiter
                        while next_c == rstring_delimiter:
                            i = self.skip_to_character(character=[rstring_delimiter, "]"], idx=i + 1)
                            next_c = self.get_char_at(i)
                            if next_c != rstring_delimiter:
                                even_delimiters = False
                                break
                            i = self.skip_to_character(character=[rstring_delimiter, "]"], idx=i + 1)
                            next_c = self.get_char_at(i)
                        if even_delimiters:
                            # If we got up to here it means that this is a situation like this:
                            # ["bla bla bla "puppy" bla bla bla "kitty" bla bla"]
                            # So we need to ignore this quote
                            self.log(
                                "While parsing a string in Array context, we detected a quoted section that would have closed the string but has a different meaning here, ignoring it",
                            )
                            unmatched_delimiter = not unmatched_delimiter
                            string_acc, char = _append_literal_char(string_acc, char)
                        else:
                            break
                    elif self.context.current == ContextValues.OBJECT_KEY:
                        # In this case we just ignore this and move on
                        self.log(
                            "While parsing a string in Object Key context, we detected a quoted section that would have closed the string but has a different meaning here, ignoring it",
                        )
                        string_acc, char = _append_literal_char(string_acc, char)
    if char and missing_quotes and self.context.current == ContextValues.OBJECT_KEY and char.isspace():
        self.log(
            "While parsing a string, handling an extreme corner case in which the LLM added a comment instead of valid string, invalidate the string and return an empty value",
        )
        self.skip_whitespaces()
        if self.get_char_at() not in [":", ","]:
            return ""

    # A fallout of the previous special case in the while loop,
    # we need to update the index only if we had a closing quote
    if char != rstring_delimiter:
        # if stream_stable = True, unclosed strings do not trim trailing whitespace characters
        if not self.stream_stable:
            self.log(
                "While parsing a string, we missed the closing quote, ignoring",
            )
            string_acc = string_acc.rstrip()
    else:
        self.index += 1

    if not self.stream_stable and (missing_quotes or (string_acc and string_acc[-1] == "\n")):
        # Clean the whitespaces for some corner cases
        string_acc = string_acc.rstrip()

    return string_acc


def _only_whitespace_until(self: "JSONParser", end: int) -> bool:
    for j in range(1, end):
        c = self.get_char_at(j)
        if c is not None and not c.isspace():
            return False
    return True
