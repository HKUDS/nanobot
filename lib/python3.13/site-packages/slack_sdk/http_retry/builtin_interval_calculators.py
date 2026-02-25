from typing import Optional
from .jitter import Jitter, RandomJitter
from .interval_calculator import RetryIntervalCalculator


class FixedValueRetryIntervalCalculator(RetryIntervalCalculator):
    """Retry interval calculator that uses a fixed value."""

    fixed_interval: float

    def __init__(self, fixed_internal: float = 0.5):
        """Retry interval calculator that uses a fixed value.

        Args:
            fixed_internal: The fixed interval seconds
        """
        self.fixed_interval = fixed_internal

    def calculate_sleep_duration(self, current_attempt: int) -> float:
        return self.fixed_interval


class BackoffRetryIntervalCalculator(RetryIntervalCalculator):
    """Retry interval calculator that calculates in the manner of Exponential Backoff And Jitter
    see also: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
    """

    backoff_factor: float
    jitter: Jitter

    def __init__(self, backoff_factor: float = 0.5, jitter: Optional[Jitter] = None):
        """Retry interval calculator that calculates in the manner of Exponential Backoff And Jitter

        Args:
            backoff_factor: The factor for the backoff interval calculation
            jitter: The jitter logic implementation
        """
        self.backoff_factor = backoff_factor
        self.jitter = jitter if jitter is not None else RandomJitter()

    def calculate_sleep_duration(self, current_attempt: int) -> float:
        interval = self.backoff_factor * (2 ** (current_attempt))
        sleep_duration = self.jitter.recalculate(interval)
        return sleep_duration
