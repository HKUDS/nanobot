from typing import TYPE_CHECKING, Any

from .utils.constants import STRING_DELIMITERS, JSONReturnType
from .utils.json_context import ContextValues
from .utils.object_comparer import ObjectComparer

if TYPE_CHECKING:
    from .json_parser import JSONParser
    from .schema_repair import SchemaRepairer


def parse_array(
    self: "JSONParser",
    schema: dict[str, Any] | bool | None = None,
    path: str = "$",
) -> list[JSONReturnType]:
    # <array> ::= '[' [ <json> *(', ' <json>) ] ']' ; A sequence of JSON values separated by commas
    # Only activate schema-guided parsing if a repairer is available and schema looks array-like.
    schema_repairer: SchemaRepairer | None = None
    items_schema: object | None = None
    additional_items: object | None = None
    if schema is not None and schema is not True:
        repairer = self.schema_repairer
        if repairer is not None:
            schema = repairer.resolve_schema(schema)
            if schema is False:
                raise ValueError("Schema does not allow any values.")
            if schema is not True and repairer.is_array_schema(schema):
                schema_repairer = repairer
                items_schema = schema.get("items")
                additional_items = schema.get("additionalItems", None)
    salvage_mode = schema_repairer is not None and schema_repairer.schema_repair_mode == "salvage"

    arr: list[JSONReturnType] = []
    self.context.set(ContextValues.ARRAY)
    self.skip_whitespaces()
    char = self.get_char_at()
    idx = 0
    while char and char not in ["]", "}"]:
        # Resolve per-item schema (tuple schemas + additionalItems) when schema guidance is active.
        item_schema: dict[str, Any] | bool | None = None
        drop_item = False
        if schema_repairer is not None:
            if isinstance(items_schema, list):
                if idx < len(items_schema):
                    raw_schema = items_schema[idx]
                    # Tuple schemas must contain dict/bool entries only.
                    if raw_schema is not None and not isinstance(raw_schema, (dict, bool)):
                        raise ValueError("Schema must be an object.")
                    item_schema = raw_schema
                else:
                    if additional_items is False:
                        drop_item = True
                    elif isinstance(additional_items, dict):
                        item_schema = additional_items
                    else:
                        item_schema = True
            elif isinstance(items_schema, dict):
                item_schema = items_schema
            else:
                item_schema = True

        item_path = f"{path}[{idx}]"
        active_schema_repairer = (
            schema_repairer if schema_repairer is not None and not drop_item and not salvage_mode else None
        )

        if char in STRING_DELIMITERS:
            # A string followed by ':' is often a missing object start; treat it as an object.
            i = 1
            i = self.skip_to_character(char, i)
            i = self.scroll_whitespaces(idx=i + 1)
            if self.get_char_at(i) == ":":
                if active_schema_repairer is not None:
                    # Schema-guided object parsing, then enforce schema on the parsed object.
                    value = self.parse_object(item_schema, item_path)
                    value = active_schema_repairer.repair_value(value, item_schema, item_path)
                else:
                    # No schema (or dropping): still parse to keep the cursor in sync.
                    value = self.parse_object()
            else:
                value = self.parse_string()
                if active_schema_repairer is not None:
                    # Apply schema constraints/coercions to scalar values when configured.
                    value = active_schema_repairer.repair_value(value, item_schema, item_path)
        else:
            # Use schema-aware parsing to guide nested repairs when configured.
            value = self.parse_json(item_schema, item_path) if active_schema_repairer is not None else self.parse_json()

        if ObjectComparer.is_strictly_empty(value) and self.get_char_at() not in ["]", ","]:
            self.index += 1
        elif value == "..." and self.get_char_at(-1) == ".":
            self.log(
                "While parsing an array, found a stray '...'; ignoring it",
            )
        elif not drop_item:
            arr.append(value)
        elif schema_repairer is not None:
            # Record drops for visibility when schema forbids extra tuple items.
            schema_repairer._log("Dropped extra array item not covered by schema", item_path)

        idx += 1
        char = self.get_char_at()
        while char and char != "]" and (char.isspace() or char == ","):
            self.index += 1
            char = self.get_char_at()

    if char != "]":
        self.log(
            "While parsing an array we missed the closing ], ignoring it",
        )

    self.index += 1
    self.context.reset()
    return arr
