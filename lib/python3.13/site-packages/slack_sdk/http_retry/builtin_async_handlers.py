import asyncio
import random
from typing import Optional, List, Type

from aiohttp import ServerDisconnectedError, ServerConnectionError, ClientOSError

from slack_sdk.http_retry.async_handler import AsyncRetryHandler
from slack_sdk.http_retry.interval_calculator import RetryIntervalCalculator
from slack_sdk.http_retry.state import RetryState
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.handler import default_interval_calculator


class AsyncConnectionErrorRetryHandler(AsyncRetryHandler):
    """RetryHandler that does retries for connectivity issues."""

    def __init__(
        self,
        max_retry_count: int = 1,
        interval_calculator: RetryIntervalCalculator = default_interval_calculator,
        error_types: List[Type[Exception]] = [
            ServerConnectionError,
            ServerDisconnectedError,
            # ClientOSError: [Errno 104] Connection reset by peer
            ClientOSError,
        ],
    ):
        super().__init__(max_retry_count, interval_calculator)
        self.error_types_to_do_retries = error_types

    async def _can_retry_async(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> bool:
        if error is None:
            return False

        for error_type in self.error_types_to_do_retries:
            if isinstance(error, error_type):
                return True
        return False


class AsyncRateLimitErrorRetryHandler(AsyncRetryHandler):
    """RetryHandler that does retries for rate limited errors."""

    async def _can_retry_async(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> bool:
        return response is not None and response.status_code == 429

    async def prepare_for_next_attempt_async(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> None:
        if response is None:
            raise error  # type: ignore[misc]

        state.next_attempt_requested = True
        retry_after_header_name: Optional[str] = None
        for k in response.headers.keys():
            if k.lower() == "retry-after":
                retry_after_header_name = k
                break
        duration = 1
        if retry_after_header_name is None:
            # This situation usually does not arise. Just in case.
            duration += random.random()  # type: ignore[assignment]
        else:
            duration = int(response.headers.get(retry_after_header_name)[0]) + random.random()  # type: ignore[assignment, index] # noqa: E501
        await asyncio.sleep(duration)
        state.increment_current_attempt()


class AsyncServerErrorRetryHandler(AsyncRetryHandler):
    """RetryHandler that does retries for server errors."""

    def __init__(
        self,
        max_retry_count: int = 1,
        interval_calculator: RetryIntervalCalculator = default_interval_calculator,
    ):
        super().__init__(max_retry_count, interval_calculator)

    async def _can_retry_async(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> bool:
        return response is not None and response.status_code in [500, 503]


def async_default_handlers() -> List[AsyncRetryHandler]:
    return [AsyncConnectionErrorRetryHandler()]
