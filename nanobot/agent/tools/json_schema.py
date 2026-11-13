"""Standards-based tool validation and actionable errors, without argument coercion."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterator
from fractions import Fraction
from functools import lru_cache
from typing import Any, cast

import regex
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


def _multiple_of(
    validator: Validator, divisor: int | float, value: Any, _schema: Any,
) -> Iterator[ValidationError]:
    if validator.is_type(value, "number"):
        # Decimal JSON spellings, not binary float fractions or an epsilon tolerance.
        quotient = Fraction(str(value)) / Fraction(str(divisor))
        if quotient.denominator != 1:
            yield ValidationError(f"{value!r} is not a multiple of {divisor}")


@lru_cache(maxsize=128)
def _pattern(expression: str) -> regex.Pattern[str]:
    return regex.compile(expression)


def _string_pattern(
    validator: Validator, expression: str, value: Any, _schema: Any,
) -> Iterator[ValidationError]:
    if validator.is_type(value, "string") and not _pattern(expression).search(value):
        yield ValidationError(f"{value!r} does not match {expression!r}")


def _check_schema(cls: type[Validator], schema: Any) -> None:
    metaschema_cls = validator_for(cls.META_SCHEMA, default=cls)
    metaschema = metaschema_cls(cls.META_SCHEMA, format_checker=cls.FORMAT_CHECKER)
    for error in metaschema.iter_errors(schema):
        # jsonschema checks regex syntax with stdlib re. String patterns use our
        # Unicode-capable engine; other schema/keyword checks remain unchanged.
        if (
            error.validator == "format" and error.validator_value == "regex"
            and error.absolute_path and error.absolute_path[-1] == "pattern"
        ):
            try:
                _pattern(error.instance)
            except regex.error:
                pass
            else:
                continue
        raise SchemaError.create_from(error)


@lru_cache(maxsize=128)
def _validator(schema_json: str) -> Validator:
    schema: dict[str, Any] | bool = json.loads(schema_json)
    if isinstance(schema, dict) and "$schema" in schema:
        if not isinstance(schema["$schema"], str):
            raise SchemaError("$schema must be a string")
        # None disables the library's fallback; its stubs only accept a class.
        cls = cast(Callable[..., type[Validator] | None], validator_for)(schema, default=None)
        if cls is None:
            raise SchemaError(f"Unsupported JSON Schema dialect: {schema['$schema']}")
    else:
        cls = Draft202012Validator
    _check_schema(cls, schema)
    # The library's factory returns a Validator class; its stubs leave extend untyped.
    cls = cast(type[Validator], extend(
        cls, validators={"multipleOf": _multiple_of, "pattern": _string_pattern},
        type_checker=cls.TYPE_CHECKER.redefine("number", _finite_number),
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
