import re
from typing import TYPE_CHECKING, Any

from .utils.constants import MISSING_VALUE, STRING_DELIMITERS, JSONReturnType
from .utils.json_context import ContextValues

if TYPE_CHECKING:
    from .json_parser import JSONParser
    from .schema_repair import SchemaRepairer


def parse_object(
    self: "JSONParser",
    schema: dict[str, Any] | bool | None = None,
    path: str = "$",
) -> JSONReturnType:
    # <object> ::= '{' [ <member> *(', ' <member>) ] '}' ; A sequence of 'members'
    obj: dict[str, JSONReturnType] = {}
    start_index = self.index

    # Only activate schema-guided parsing if a repairer is available and schema looks object-like.
    schema_repairer: SchemaRepairer | None = None
    properties: dict[str, Any] = {}
    pattern_properties: dict[str, Any] = {}
    additional_properties: object | None = None
    required: set[str] = set()

    if schema is not None and schema is not True:
        repairer = self.schema_repairer
        if repairer is not None:
            schema = repairer.resolve_schema(schema)
            if schema is False:
                raise ValueError("Schema does not allow any values.")
            if schema is not True and repairer.is_object_schema(schema):
                schema_repairer = repairer
                properties = schema.get("properties", {})
                if not isinstance(properties, dict):
                    properties = {}
                pattern_properties = schema.get("patternProperties", {})
                if not isinstance(pattern_properties, dict):
                    pattern_properties = {}
                additional_properties = schema.get("additionalProperties", None)
                required = set(schema.get("required", []))

    def finalize_obj() -> dict[str, JSONReturnType]:
        if schema_repairer is None:
            return obj
        schema_repairer_local = schema_repairer
        # Enforce required fields and insert defaults for optional properties.
        missing_required = [key for key in required if key not in obj]
        if missing_required:
            raise ValueError(f"Missing required properties at {path}: {', '.join(missing_required)}")
        for key, prop_schema in properties.items():
            if key in obj or key in required:
                continue
            if isinstance(prop_schema, dict) and "default" in prop_schema:
                obj[key] = schema_repairer_local._copy_json_value(prop_schema["default"], f"{path}.{key}", "default")
                schema_repairer_local._log("Inserted default value for missing property", f"{path}.{key}")
        return obj

    # Stop when you either find the closing parentheses or you have iterated over the entire string
    while (self.get_char_at() or "}") != "}":
        # This is what we expect to find:
        # <member> ::= <string> ': ' <json>

        # Skip filler whitespaces
        self.skip_whitespaces()

        # Sometimes LLMs do weird things, if we find a ":" so early, we'll change it to "," and move on
        if self.get_char_at() == ":":
            self.log(
                "While parsing an object we found a : before a key, ignoring",
            )
            self.index += 1

        # We are now searching for they string key
        # Context is used in the string parser to manage the lack of quotes
        self.context.set(ContextValues.OBJECT_KEY)

        # Save this index in case we need find a duplicate key
        rollback_index = self.index

        # <member> starts with a <string>
        key = ""
        while self.get_char_at():
            # The rollback index needs to be updated here in case the key is empty
            rollback_index = self.index
            if self.get_char_at() == "[" and key == "":
                # Is this an array?
                # Need to check if the previous parsed value contained in obj is an array and in that case parse and merge the two
                prev_key = list(obj.keys())[-1] if obj else None
                if prev_key and isinstance(obj[prev_key], list) and not self.strict:
                    # If the previous key's value is an array, parse the new array and merge
                    self.index += 1
                    new_array = self.parse_array()
                    if isinstance(new_array, list):
                        # Merge and flatten the arrays
                        prev_value = obj[prev_key]
                        if isinstance(prev_value, list):
                            list_lengths = [len(item) for item in prev_value if isinstance(item, list)]
                            expected_len = (
                                list_lengths[0]
                                if list_lengths and all(length == list_lengths[0] for length in list_lengths)
                                else None
                            )
                            if expected_len:
                                # Matrix-style JSON: list of uniform-length rows.
                                # Repair a missing inner "[" by regrouping trailing scalar cells into rows.
                                tail = []
                                while prev_value and not isinstance(prev_value[-1], list):
                                    tail.append(prev_value.pop())
                                if tail:
                                    tail.reverse()
                                    if len(tail) % expected_len == 0:
                                        self.log(
                                            "While parsing an object we found row values without an inner array, grouping them into rows",
                                        )
                                        for i in range(0, len(tail), expected_len):
                                            prev_value.append(tail[i : i + expected_len])
                                    else:
                                        prev_value.extend(tail)
                                # Keep incoming rows as rows instead of flattening them into the table.
                                if new_array:
                                    if all(isinstance(item, list) for item in new_array):
                                        self.log(
                                            "While parsing an object we found additional rows, appending them without flattening",
                                        )
                                        prev_value.extend(new_array)
                                    else:
                                        prev_value.append(new_array)
                            else:
                                # Fallback to legacy merge behavior when not a uniform row list or in strict mode.
                                prev_value.extend(
                                    new_array[0]
                                    if len(new_array) == 1 and isinstance(new_array[0], list)
                                    else new_array
                                )
                    self.skip_whitespaces()
                    if self.get_char_at() == ",":
                        self.index += 1
                    self.skip_whitespaces()
                    continue
            raw_key = self.parse_string()
            assert isinstance(raw_key, str)
            key = raw_key
            if key == "":
                self.skip_whitespaces()
            if key != "" or (key == "" and self.get_char_at() in [":", "}"]):
                # Empty keys now trigger in strict mode, otherwise we keep repairing as before
                if key == "" and self.strict:
                    self.log(
                        "Empty key found in strict mode while parsing object, raising an error",
                    )
                    raise ValueError("Empty key found in strict mode while parsing object.")
                break
        if ContextValues.ARRAY in self.context.context and key in obj:
            if self.strict:
                self.log("Duplicate key found in strict mode while parsing object, raising an error")
                raise ValueError("Duplicate key found in strict mode while parsing object.")
            self.log(
                "While parsing an object we found a duplicate key, closing the object here and rolling back the index",
            )
            self.index = rollback_index - 1
            # add an opening curly brace to make this work
            self.json_str = self.json_str[: self.index + 1] + "{" + self.json_str[self.index + 1 :]
            break

        # Skip filler whitespaces
        self.skip_whitespaces()

        # We reached the end here
        if (self.get_char_at() or "}") == "}":
            continue

        self.skip_whitespaces()

        # An extreme case of missing ":" after a key
        if self.get_char_at() != ":":
            if self.strict:
                self.log(
                    "Missing ':' after key in strict mode while parsing object, raising an error",
                )
                raise ValueError("Missing ':' after key in strict mode while parsing object.")
            self.log(
                "While parsing an object we missed a : after a key",
            )

        self.index += 1
        self.context.reset()
        self.context.set(ContextValues.OBJECT_VALUE)
        # The value can be any valid json; strict mode will refuse repaired empties
        self.skip_whitespaces()
        # Corner case, a lone comma
        value: JSONReturnType = ""
        prop_schema: dict[str, Any] | bool | None = None
        extra_schemas: list[dict[str, Any] | bool | None] = []
        drop_property = False

        if schema_repairer is not None:
            if key in properties:
                schema_value = properties[key]
                # Schema entries must be dict/bool; reject invalid metadata early.
                if schema_value is not None and not isinstance(schema_value, (dict, bool)):
                    raise ValueError("Schema must be an object.")
                prop_schema = schema_value
            else:
                matched = [
                    schema_value for pattern, schema_value in pattern_properties.items() if re.search(pattern, key)
                ]
                if matched:
                    # patternProperties can stack: apply the first schema, then any extras in order.
                    primary_schema = matched[0]
                    if primary_schema is not None and not isinstance(primary_schema, (dict, bool)):
                        raise ValueError("Schema must be an object.")
                    prop_schema = primary_schema
                    for extra_schema in matched[1:]:
                        if extra_schema is not None and not isinstance(extra_schema, (dict, bool)):
                            raise ValueError("Schema must be an object.")
                        extra_schemas.append(extra_schema)
                else:
                    if additional_properties is False:
                        # Schema forbids unknown keys: parse but drop this property.
                        drop_property = True
                    elif isinstance(additional_properties, dict):
                        prop_schema = additional_properties
                    else:
                        prop_schema = True

        char = self.get_char_at()
        key_path = f"{path}.{key}"
        if char in [",", "}"]:
            self.log(
                f"While parsing an object value we found a stray {char}, ignoring it",
            )
            if schema_repairer is not None:
                # Missing value: fill according to schema (defaults/const/enum/type).
                value = schema_repairer.repair_value(MISSING_VALUE, prop_schema, key_path)
        else:
            # Schema-aware parsing guides repairs inside nested values.
            value = self.parse_json(prop_schema, key_path) if schema_repairer is not None else self.parse_json()

        if schema_repairer is not None and extra_schemas:
            # Apply any additional pattern schemas in order.
            for extra_schema in extra_schemas:
                value = schema_repairer.repair_value(value, extra_schema, key_path)

        if schema_repairer is None and value == "" and self.strict and self.get_char_at(-1) not in STRING_DELIMITERS:
            self.log(
                "Parsed value is empty in strict mode while parsing object, raising an error",
            )
            raise ValueError("Parsed value is empty in strict mode while parsing object.")

        # Reset context since our job is done
        self.context.reset()
        if schema_repairer is None or not drop_property:
            obj[key] = value
        else:
            # Keep parsing but omit forbidden properties to respect the schema.
            schema_repairer._log("Dropped extra property not covered by schema", key_path)

        if self.get_char_at() in [",", "'", '"']:
            self.index += 1
        if self.get_char_at() == "]" and ContextValues.ARRAY in self.context.context:
            self.log(
                "While parsing an object we found a closing array bracket, closing the object here and rolling back the index"
            )
            self.index -= 1
            break
        # Remove trailing spaces
        self.skip_whitespaces()

    self.index += 1

    # If the object is empty but also isn't just {}
    if not obj and self.index - start_index > 2:
        if self.strict:
            self.log(
                "Parsed object is empty but contains extra characters in strict mode, raising an error",
            )
            raise ValueError("Parsed object is empty but contains extra characters in strict mode.")
        self.log("Parsed object is empty, we will try to parse this as an array instead")
        self.index = start_index
        return self.parse_array()

    # Check if there are more key-value pairs after the closing brace
    # This handles cases like '{"key": "value"}, "key2": "value2"}'
    # But only if we're not in a nested context
    if not self.context.empty:
        # Sometimes there could be an extra closing brace that closes the object twice
        # So we check the context to see if the next one in the stack is an object or not
        # If not we skip it
        if self.get_char_at() == "}" and self.context.current not in [
            ContextValues.OBJECT_KEY,
            ContextValues.OBJECT_VALUE,
        ]:
            self.log(
                "Found an extra closing brace that shouldn't be there, skipping it",
            )
            self.index += 1
        return obj

    self.skip_whitespaces()
    if self.get_char_at() != ",":
        return finalize_obj()
    self.index += 1
    self.skip_whitespaces()
    if self.get_char_at() not in STRING_DELIMITERS:
        return finalize_obj()
    if not self.strict:
        self.log(
            "Found a comma and string delimiter after object closing brace, checking for additional key-value pairs",
        )
        additional_obj = self.parse_object(schema, path)
        if isinstance(additional_obj, dict):
            obj.update(additional_obj)

    return finalize_obj()
