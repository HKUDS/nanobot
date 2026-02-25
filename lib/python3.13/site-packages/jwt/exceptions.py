class PyJWTError(Exception):
    """
    Base class for all exceptions
    """

    pass


class InvalidTokenError(PyJWTError):
    """Base exception when ``decode()`` fails on a token"""

    pass


class DecodeError(InvalidTokenError):
    """Raised when a token cannot be decoded because it failed validation"""

    pass


class InvalidSignatureError(DecodeError):
    """Raised when a token's signature doesn't match the one provided as part of
    the token."""

    pass


class ExpiredSignatureError(InvalidTokenError):
    """Raised when a token's ``exp`` claim indicates that it has expired"""

    pass


class InvalidAudienceError(InvalidTokenError):
    """Raised when a token's ``aud`` claim does not match one of the expected
    audience values"""

    pass


class InvalidIssuerError(InvalidTokenError):
    """Raised when a token's ``iss`` claim does not match the expected issuer"""

    pass


class InvalidIssuedAtError(InvalidTokenError):
    """Raised when a token's ``iat`` claim is non-numeric"""

    pass


class ImmatureSignatureError(InvalidTokenError):
    """Raised when a token's ``nbf`` or ``iat`` claims represent a time in the future"""

    pass


class InvalidKeyError(PyJWTError):
    """Raised when the specified key is not in the proper format"""

    pass


class InvalidAlgorithmError(InvalidTokenError):
    """Raised when the specified algorithm is not recognized by PyJWT"""

    pass


class MissingRequiredClaimError(InvalidTokenError):
    """Raised when a claim that is required to be present is not contained
    in the claimset"""

    def __init__(self, claim: str) -> None:
        self.claim = claim

    def __str__(self) -> str:
        return f'Token is missing the "{self.claim}" claim'


class PyJWKError(PyJWTError):
    pass


class MissingCryptographyError(PyJWKError):
    """Raised if the algorithm requires ``cryptography`` to be installed and it is not available."""

    pass


class PyJWKSetError(PyJWTError):
    pass


class PyJWKClientError(PyJWTError):
    pass


class PyJWKClientConnectionError(PyJWKClientError):
    pass


class InvalidSubjectError(InvalidTokenError):
    """Raised when a token's ``sub`` claim is not a string or doesn't match the expected ``subject``"""

    pass


class InvalidJTIError(InvalidTokenError):
    """Raised when a token's ``jti`` claim is not a string"""

    pass
