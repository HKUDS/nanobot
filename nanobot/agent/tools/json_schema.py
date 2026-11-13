"""Standards-based tool validation and actionable errors, without argument coercion."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from functools import lru_cache
from typing import Any, cast

from jsonschema import Draft202012Validator, TypeChecker
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.protocols import Validator
from jsonschema.validators import (
    extend,  # pyright: ignore[reportUnknownVariableType]
    validator_for,
)
from referencing import Registry
from referencing.exceptions import Unresolvable


def _finite_number(_checker: TypeChecker, value: Any) -> bool:
    # Python's JSON decoder accepts NaN/Infinity, but JSON numbers must be finite.
    return Draft202012Validator.TYPE_CHECKER.is_type(value, "number") and (
        not isinstance(value, float) or math.isfinite(value)
    )


@lru_cache(maxsize=128)
def _validator(schema_json: str) -> Validator:
    schema = json.loads(schema_json)
    cls = validator_for(schema, default=Draft202012Validator)
    cls.check_schema(schema)
    # The library's factory returns a Validator class; its stubs leave extend untyped.
    cls = cast(type[Validator], extend(
        cls, type_checker=cls.TYPE_CHECKER.redefine("number", _finite_number),
    ))
    # An empty registry resolves in-document refs only, without HTTP or file retrieval.
    return cls(schema, registry=Registry[Any]())


def _error_messages(error: ValidationError, path: str) -> Iterator[str]:
    suffix = error.json_path.removeprefix("$")
    label = f"{path}{suffix}" if path else suffix.removeprefix(".")
    yield f"{label or 'parameters'}: {error.message}"
    for child in error.context:
        yield from _error_messages(child, path)


def validate_value(value: Any, schema: dict[str, Any] | bool, path: str = "") -> list[str]:
    """Validate with the declared dialect (2020-12 by default); return model-facing errors."""
    try:
        validator = _validator(json.dumps(schema))
        return list(dict.fromkeys(
            message
            for error in validator.iter_errors(value)
            for message in _error_messages(error, path)
        ))
    except SchemaError as exc:
        return [f"Invalid tool schema: {exc.message}"]
    except Unresolvable as exc:
        return [f"Invalid tool schema: cannot resolve reference {exc}"]
