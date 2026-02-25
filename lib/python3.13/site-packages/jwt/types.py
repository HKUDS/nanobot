from typing import Any, Callable, TypedDict

JWKDict = dict[str, Any]

HashlibHash = Callable[..., Any]


class SigOptions(TypedDict, total=False):
    """Options for PyJWS class (TypedDict). Note that this is a smaller set of options than
    for :py:func:`jwt.decode()`."""

    verify_signature: bool
    """verify the JWT cryptographic signature"""
    enforce_minimum_key_length: bool
    """Default: ``False``. Raise :py:class:`jwt.exceptions.InvalidKeyError` instead of warning when keys are below minimum recommended length."""


class Options(TypedDict, total=False):
    """Options for :py:func:`jwt.decode()` and :py:func:`jwt.api_jwt.decode_complete()` (TypedDict).

    .. warning::

        Some claims, such as ``exp``, ``iat``, ``jti``, ``nbf``, and ``sub``,
        will only be verified if present. Please refer to the documentation below
        for which ones, and make sure to include them in the ``require`` param
        if you want to make sure that they are always present (and therefore always verified
        if ``verify_{claim} = True`` for that claim).
    """

    verify_signature: bool
    """Default: ``True``. Verify the JWT cryptographic signature."""
    require: list[str]
    """Default: ``[]``. List of claims that must be present.
          Example: ``require=["exp", "iat", "nbf"]``.
          **Only verifies that the claims exists**. Does not verify that the claims are valid."""
    strict_aud: bool
    """Default: ``False``. (requires ``verify_aud=True``) Check that the ``aud`` claim is a single value (not a list), and matches ``audience`` exactly."""
    verify_aud: bool
    """Default: ``verify_signature``. Check that ``aud`` (audience) claim matches ``audience``."""
    verify_exp: bool
    """Default: ``verify_signature``. Check that ``exp`` (expiration) claim value is in the future (if present in payload). """
    verify_iat: bool
    """Default: ``verify_signature``. Check that ``iat`` (issued at) claim value is an integer (if present in payload). """
    verify_iss: bool
    """Default: ``verify_signature``. Check that ``iss`` (issuer) claim matches ``issuer``. """
    verify_jti: bool
    """Default: ``verify_signature``. Check that ``jti`` (JWT ID) claim is a string (if present in payload). """
    verify_nbf: bool
    """Default: ``verify_signature``. Check that ``nbf`` (not before) claim value is in the past (if present in payload). """
    verify_sub: bool
    """Default: ``verify_signature``. Check that ``sub`` (subject) claim is a string and matches ``subject`` (if present in payload). """
    enforce_minimum_key_length: bool
    """Default: ``False``. Raise :py:class:`jwt.exceptions.InvalidKeyError` instead of warning when keys are below minimum recommended length."""


# The only difference between Options and FullOptions is that FullOptions
# required _every_ value to be there; Options doesn't require any
class FullOptions(TypedDict):
    verify_signature: bool
    require: list[str]
    strict_aud: bool
    verify_aud: bool
    verify_exp: bool
    verify_iat: bool
    verify_iss: bool
    verify_jti: bool
    verify_nbf: bool
    verify_sub: bool
    enforce_minimum_key_length: bool
