"""
This module will parse the JSON file following the BNF definition:

    <json> ::= <container>

    <primitive> ::= <number> | <string> | <boolean>
    ; Where:
    ; <number> is a valid real number expressed in one of a number of given formats
    ; <string> is a string of valid characters enclosed in quotes
    ; <boolean> is one of the literal strings 'true', 'false', or 'null' (unquoted)

    <container> ::= <object> | <array>
    <array> ::= '[' [ <json> *(', ' <json>) ] ']' ; A sequence of JSON values separated by commas
    <object> ::= '{' [ <member> *(', ' <member>) ] '}' ; A sequence of 'members'
    <member> ::= <string> ': ' <json> ; A pair consisting of a name, and a JSON value

If something is wrong (a missing parentheses or quotes for example) it will use a few simple heuristics to fix the JSON string:
- Add the missing parentheses if the parser believes that the array or object should be closed
- Quote strings or add missing single quotes
- Adjust whitespaces and remove line breaks

All supported use cases are in the unit tests
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal, TextIO, overload

from .json_parser import JSONParser
from .schema_repair import SchemaRepairer, load_schema_model, normalize_schema_repair_mode, schema_from_input
from .utils.constants import JSONReturnType


@overload
def repair_json(
    json_str: str = "",
    return_objects: Literal[False] = False,
    skip_json_loads: bool = False,
    logging: bool = False,
    json_fd: TextIO | None = None,
    chunk_length: int = 0,
    stream_stable: bool = False,
    strict: bool = False,
    schema: Any | None = None,
    schema_repair_mode: Literal["standard", "salvage"] = "standard",
    **json_dumps_args: Any,
) -> str: ...


@overload
def repair_json(
    json_str: str = "",
    return_objects: Literal[True] = True,
    skip_json_loads: bool = False,
    logging: bool = False,
    json_fd: TextIO | None = None,
    chunk_length: int = 0,
    stream_stable: bool = False,
    strict: bool = False,
    schema: Any | None = None,
    schema_repair_mode: Literal["standard", "salvage"] = "standard",
    **json_dumps_args: Any,
) -> JSONReturnType | tuple[JSONReturnType, list[dict[str, str]]]: ...


def repair_json(
    json_str: str = "",
    return_objects: bool = False,
    skip_json_loads: bool = False,
    logging: bool = False,
    json_fd: TextIO | None = None,
    chunk_length: int = 0,
    stream_stable: bool = False,
    strict: bool = False,
    schema: Any | None = None,
    schema_repair_mode: Literal["standard", "salvage"] = "standard",
    **json_dumps_args: Any,
) -> JSONReturnType | tuple[JSONReturnType, list[dict[str, str]]]:
    """
    Given a json formatted string, it will try to decode it and, if it fails, it will try to fix it.

    Args:
        json_str (str, optional): The JSON string to repair. Defaults to an empty string.
        return_objects (bool, optional): If True, return the decoded data structure. Defaults to False.
        skip_json_loads (bool, optional): If True, skip calling the built-in json.loads() function to verify that the json is valid before attempting to repair. Defaults to False.
        logging (bool, optional): If True, return a tuple with the repaired json and a log of all repair actions. Defaults to False. When no repairs were required, the repair log will be an empty list.
        json_fd (Optional[TextIO], optional): File descriptor for JSON input. Do not use! Use `from_file` or `load` instead. Defaults to None.
        ensure_ascii (bool, optional): Set to False to avoid converting non-latin characters to ascii (for example when using chinese characters). Defaults to True. Ignored if `skip_json_loads` is True.
        chunk_length (int, optional): Size in bytes of the file chunks to read at once. Ignored if `json_fd` is None. Do not use! Use `from_file` or `load` instead. Defaults to 1MB.
        stream_stable (bool, optional): When the json to be repaired is the accumulation of streaming json at a certain moment.If this parameter to True will keep the repair results stable.
        strict (bool, optional): If True, surface structural problems (duplicate keys, missing separators, empty keys/values, etc.) as ValueError instead of repairing them.
        schema (Any, optional): JSON Schema dict, boolean schema, or pydantic v2 model used to guide repairs and validation for both valid and invalid JSON inputs.
        schema_repair_mode (Literal["standard", "salvage"], optional): Schema repair mode. "standard" keeps default schema behavior; "salvage" enables best-effort schema salvage heuristics for arrays/objects.
    Returns:
        Union[JSONReturnType, Tuple[JSONReturnType, List[Dict[str, str]]]]: The repaired JSON or a tuple with the repaired JSON and repair log when logging is True.
    """
    schema_repair_mode = normalize_schema_repair_mode(schema_repair_mode)
    if schema is None and schema_repair_mode == "salvage":
        raise ValueError("schema_repair_mode='salvage' requires schema.")

    # Schema-guided repairs and strict mode are mutually exclusive to avoid conflicting behavior.
    if schema is not None and strict:
        raise ValueError("schema and strict cannot be used together.")

    parser = JSONParser(json_str, json_fd, logging, chunk_length, stream_stable, strict)
    schema_obj = schema_from_input(schema) if schema is not None else None
    repairer = (
        SchemaRepairer(schema_obj, parser.logger if logging else None, schema_repair_mode=schema_repair_mode)
        if schema_obj is not None
        else None
    )

    # Fast path for valid JSON: schema-aware mode still applies repair+validation.
    parsed_json: JSONReturnType = None
    is_valid_json = False
    try:
        if not skip_json_loads:
            parsed_json = json.load(json_fd) if json_fd else json.loads(json_str)
            if repairer is not None and schema_obj is not None:
                # Validate here to ensure that we reject values that cannot satisfy the schema and fall back to the more expensive parser+schema repair if needed, instead of just returning the valid but schema-noncompliant JSON.
                repairer.validate(parsed_json, schema_obj)
            is_valid_json = True
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    if not is_valid_json:
        if repairer is not None and schema_obj is not None:
            # If schema-guided, we want to attempt repairs even on valid JSON that fails schema validation.
            parsed_json = parser.parse_with_schema(repairer, schema_obj)
            repairer.validate(parsed_json, schema_obj)
        else:
            # Otherwise, we can skip the more expensive schema-aware parsing and just do a normal parse.
            parsed_json = parser.parse()

    # It's useful to return the actual object instead of the json string,
    # it allows this lib to be a replacement of the json library
    if logging:
        return parsed_json, parser.logger or []
    if return_objects:
        return parsed_json
    # Avoid returning only a pair of quotes if it's an empty string
    if parsed_json == "":
        return ""
    return json.dumps(parsed_json, **json_dumps_args)


def loads(
    json_str: str,
    skip_json_loads: bool = False,
    logging: bool = False,
    stream_stable: bool = False,
    strict: bool = False,
    schema: Any | None = None,
    schema_repair_mode: Literal["standard", "salvage"] = "standard",
) -> JSONReturnType | tuple[JSONReturnType, list[dict[str, str]]] | str:
    """
    This function works like `json.loads()` except that it will fix your JSON in the process.
    It is a wrapper around the `repair_json()` function with `return_objects=True`.

    Args:
        json_str (str): The JSON string to load and repair.
        skip_json_loads (bool, optional): If True, skip calling the built-in json.loads() function to verify that the json is valid before attempting to repair. Defaults to False.
        logging (bool, optional): If True, return a tuple with the repaired json and a log of all repair actions. Defaults to False.
        strict (bool, optional): If True, surface structural problems (duplicate keys, missing separators, empty keys/values, etc.) as ValueError instead of repairing them.
        schema (Any, optional): JSON Schema dict, boolean schema, or pydantic v2 model used to guide repairs and validation for both valid and invalid JSON inputs.
        schema_repair_mode (Literal["standard", "salvage"], optional): Schema repair mode. "salvage" requires schema.

    Returns:
        Union[JSONReturnType, Tuple[JSONReturnType, List[Dict[str, str]]], str]: The repaired JSON object or a tuple with the repaired JSON object and repair log.
    """
    return repair_json(
        json_str=json_str,
        return_objects=True,
        skip_json_loads=skip_json_loads,
        logging=logging,
        stream_stable=stream_stable,
        strict=strict,
        schema=schema,
        schema_repair_mode=schema_repair_mode,
    )


def load(
    fd: TextIO,
    skip_json_loads: bool = False,
    logging: bool = False,
    chunk_length: int = 0,
    strict: bool = False,
    schema: Any | None = None,
    schema_repair_mode: Literal["standard", "salvage"] = "standard",
) -> JSONReturnType | tuple[JSONReturnType, list[dict[str, str]]]:
    """
    This function works like `json.load()` except that it will fix your JSON in the process.
    It is a wrapper around the `repair_json()` function with `json_fd=fd` and `return_objects=True`.

    Args:
        fd (TextIO): File descriptor for JSON input.
        skip_json_loads (bool, optional): If True, skip calling the built-in json.loads() function to verify that the json is valid before attempting to repair. Defaults to False.
        logging (bool, optional): If True, return a tuple with the repaired json and a log of all repair actions. Defaults to False.
        chunk_length (int, optional): Size in bytes of the file chunks to read at once. Defaults to 1MB.
        strict (bool, optional): If True, surface structural problems (duplicate keys, missing separators, empty keys/values, etc.) as ValueError instead of repairing them.
        schema (Any, optional): JSON Schema dict, boolean schema, or pydantic v2 model used to guide repairs and validation for both valid and invalid JSON inputs.
        schema_repair_mode (Literal["standard", "salvage"], optional): Schema repair mode. "salvage" requires schema.

    Returns:
        Union[JSONReturnType, Tuple[JSONReturnType, List[Dict[str, str]]]]: The repaired JSON object or a tuple with the repaired JSON object and repair log.
    """
    return repair_json(
        json_fd=fd,
        chunk_length=chunk_length,
        return_objects=True,
        skip_json_loads=skip_json_loads,
        logging=logging,
        strict=strict,
        schema=schema,
        schema_repair_mode=schema_repair_mode,
    )


def from_file(
    filename: str | Path,
    skip_json_loads: bool = False,
    logging: bool = False,
    chunk_length: int = 0,
    strict: bool = False,
    schema: Any | None = None,
    schema_repair_mode: Literal["standard", "salvage"] = "standard",
) -> JSONReturnType | tuple[JSONReturnType, list[dict[str, str]]]:
    """
    This function is a wrapper around `load()` so you can pass the filename as string

    Args:
        filename (str | Path): The name of the file containing JSON data to load and repair.
        skip_json_loads (bool, optional): If True, skip calling the built-in json.loads() function to verify that the json is valid before attempting to repair. Defaults to False.
        logging (bool, optional): If True, return a tuple with the repaired json and a log of all repair actions. Defaults to False.
        chunk_length (int, optional): Size in bytes of the file chunks to read at once. Defaults to 1MB.
        strict (bool, optional): If True, surface structural problems (duplicate keys, missing separators, empty keys/values, etc.) as ValueError instead of repairing them.
        schema (Any, optional): JSON Schema dict, boolean schema, or pydantic v2 model used to guide repairs and validation for both valid and invalid JSON inputs.
        schema_repair_mode (Literal["standard", "salvage"], optional): Schema repair mode. "salvage" requires schema.

    Returns:
        Union[JSONReturnType, Tuple[JSONReturnType, List[Dict[str, str]]]]: The repaired JSON object or a tuple with the repaired JSON object and repair log.
    """
    with Path(filename).open() as fd:
        return load(
            fd=fd,
            skip_json_loads=skip_json_loads,
            logging=logging,
            chunk_length=chunk_length,
            strict=strict,
            schema=schema,
            schema_repair_mode=schema_repair_mode,
        )


def cli(inline_args: list[str] | None = None) -> int:
    """
    Command-line interface for repairing and parsing JSON files.

    Args:
        inline_args (Optional[List[str]]): List of command-line arguments for testing purposes. Defaults to None.
            - filename (str): The JSON file to repair. If omitted, the JSON is read from stdin.
            - -i, --inline (bool): Replace the file inline instead of returning the output to stdout.
            - -o, --output TARGET (str): If specified, the output will be written to TARGET filename instead of stdout.
            - --ensure_ascii (bool): Pass ensure_ascii=True to json.dumps(). Will pass False otherwise.
            - --indent INDENT (int): Number of spaces for indentation (Default 2).
            - --skip-json-loads (bool): Skip initial json.loads validation.
            - --schema SCHEMA (str): Path to a JSON Schema file that guides repairs.
            - --schema-model MODEL (str): Pydantic v2 model in 'module:ClassName' form that guides repairs.
            - --strict (bool): Raise on duplicate keys, missing separators, empty keys/values, and other unrecoverable structures instead of repairing them.

    Returns:
        int: Exit code of the CLI operation.

    Raises:
        Exception: Any exception that occurs during file processing.

    Example:
        >>> cli(['example.json', '--indent', '4'])
        >>> cat json.txt | json_repair
    """
    parser = argparse.ArgumentParser(description="Repair and parse JSON files.")
    # Make the filename argument optional; if omitted, we will read from stdin.
    parser.add_argument(
        "filename",
        nargs="?",
        help="The JSON file to repair (if omitted, reads from stdin)",
    )
    parser.add_argument(
        "-i",
        "--inline",
        action="store_true",
        help="Replace the file inline instead of returning the output to stdout",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="TARGET",
        help="If specified, the output will be written to TARGET filename instead of stdout",
    )
    parser.add_argument(
        "--ensure_ascii",
        action="store_true",
        help="Pass ensure_ascii=True to json.dumps()",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Number of spaces for indentation (Default 2)",
    )
    parser.add_argument(
        "--skip-json-loads",
        action="store_true",
        help="Skip initial json.loads validation",
    )
    parser.add_argument(
        "--schema",
        metavar="SCHEMA",
        help="Path to a JSON Schema file that guides repairs",
    )
    parser.add_argument(
        "--schema-model",
        metavar="MODEL",
        help="Pydantic v2 model in 'module:ClassName' form that guides repairs",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Raise on duplicate keys, missing separators, empty keys/values, and other unrecoverable structures instead of repairing them",
    )
    parser.add_argument(
        "--schema-repair-mode",
        choices=["standard", "salvage"],
        default="standard",
        help="Schema repair mode: 'standard' (default) or 'salvage' (best-effort array/object salvage).",
    )

    args = parser.parse_args(inline_args)

    # Inline mode requires a filename, so error out if none was provided.
    if args.inline and not args.filename:  # pragma: no cover
        print("Error: Inline mode requires a filename", file=sys.stderr)
        sys.exit(1)

    if args.inline and args.output:  # pragma: no cover
        print("Error: You cannot pass both --inline and --output", file=sys.stderr)
        sys.exit(1)

    if args.schema and args.schema_model:
        print("Error: You cannot pass both --schema and --schema-model", file=sys.stderr)
        sys.exit(1)

    if args.strict and (args.schema or args.schema_model):
        print("Error: --strict cannot be used with --schema or --schema-model", file=sys.stderr)
        sys.exit(1)
    if args.schema_repair_mode == "salvage" and not (args.schema or args.schema_model):
        print("Error: --schema-repair-mode salvage requires --schema or --schema-model", file=sys.stderr)
        sys.exit(1)

    ensure_ascii = args.ensure_ascii

    try:
        schema = None
        if args.schema:
            with Path(args.schema).open() as fd:
                schema = json.load(fd)
        elif args.schema_model:
            schema = load_schema_model(args.schema_model)

        # Use from_file if a filename is provided; otherwise read from stdin.
        if args.filename:
            result = from_file(
                args.filename,
                skip_json_loads=args.skip_json_loads,
                strict=args.strict,
                schema=schema,
                schema_repair_mode=args.schema_repair_mode,
            )
        else:
            data = sys.stdin.read()
            result = loads(
                data,
                skip_json_loads=args.skip_json_loads,
                strict=args.strict,
                schema=schema,
                schema_repair_mode=args.schema_repair_mode,
            )
        if args.inline or args.output:
            with Path(args.output or args.filename).open(mode="w") as fd:
                json.dump(result, fd, indent=args.indent, ensure_ascii=ensure_ascii)
        else:
            print(json.dumps(result, indent=args.indent, ensure_ascii=ensure_ascii))
    except (OSError, TypeError, ValueError) as e:  # pragma: no cover
        print(f"Error: {str(e)}", file=sys.stderr)
        return 1

    return 0  # Success


if __name__ == "__main__":  # pragma: no cover
    sys.exit(cli())
