from typing import List

from .handler import RetryHandler
from .builtin_handlers import (
    ConnectionErrorRetryHandler,
    RateLimitErrorRetryHandler,
)
from .interval_calculator import RetryIntervalCalculator
from .builtin_interval_calculators import (
    FixedValueRetryIntervalCalculator,
    BackoffRetryIntervalCalculator,
)
from .jitter import Jitter
from .request import HttpRequest
from .response import HttpResponse
from .state import RetryState

connect_error_retry_handler = ConnectionErrorRetryHandler()
rate_limit_error_retry_handler = RateLimitErrorRetryHandler()


def default_retry_handlers() -> List[RetryHandler]:
    return [connect_error_retry_handler]


def all_builtin_retry_handlers() -> List[RetryHandler]:
    return [
        connect_error_retry_handler,
        rate_limit_error_retry_handler,
    ]


__all__ = [
    "RetryHandler",
    "ConnectionErrorRetryHandler",
    "RateLimitErrorRetryHandler",
    "RetryIntervalCalculator",
    "FixedValueRetryIntervalCalculator",
    "BackoffRetryIntervalCalculator",
    "Jitter",
    "HttpRequest",
    "HttpResponse",
    "RetryState",
    "connect_error_retry_handler",
    "rate_limit_error_retry_handler",
    "default_retry_handlers",
    "all_builtin_retry_handlers",
]
