"""asyncio compatible RetryHandler interface.
You can pass an array of handlers to customize retry logics in supported API clients.
"""

import asyncio
from typing import Optional

from slack_sdk.http_retry.state import RetryState
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.interval_calculator import RetryIntervalCalculator
from slack_sdk.http_retry.builtin_interval_calculators import (
    BackoffRetryIntervalCalculator,
)

default_interval_calculator = BackoffRetryIntervalCalculator()


class AsyncRetryHandler:
    """asyncio compatible RetryHandler interface.
    You can pass an array of handlers to customize retry logics in supported API clients.
    """

    max_retry_count: int
    interval_calculator: RetryIntervalCalculator

    def __init__(
        self,
        max_retry_count: int = 1,
        interval_calculator: RetryIntervalCalculator = default_interval_calculator,
    ):
        """RetryHandler interface.

        Args:
            max_retry_count: The maximum times to do retries
            interval_calculator: Pass an interval calculator for customizing the logic
        """
        self.max_retry_count = max_retry_count
        self.interval_calculator = interval_calculator

    async def can_retry_async(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> bool:
        if state.current_attempt >= self.max_retry_count:
            return False
        return await self._can_retry_async(
            state=state,
            request=request,
            response=response,
            error=error,
        )

    async def _can_retry_async(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> bool:
        raise NotImplementedError()

    async def prepare_for_next_attempt_async(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> None:
        state.next_attempt_requested = True
        duration = self.interval_calculator.calculate_sleep_duration(state.current_attempt)
        await asyncio.sleep(duration)
        state.increment_current_attempt()


__all__ = [
    "RetryState",
    "HttpRequest",
    "HttpResponse",
    "RetryIntervalCalculator",
    "BackoffRetryIntervalCalculator",
    "default_interval_calculator",
]
