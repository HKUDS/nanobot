"""Rate limiter for controlling API call frequency."""

import asyncio
import time


class RateLimiter:
    """
    Simple fixed-delay rate limiter.
    
    Ensures API calls are spaced out to respect provider rate limits.
    Uses a fixed minimum delay between calls based on requests per minute.
    
    Example:
        >>> limiter = RateLimiter(requests_per_minute=30)
        >>> await limiter.acquire()  # First call - no delay
        >>> await limiter.acquire()  # Second call - waits ~2 seconds
    """
    
    def __init__(self, requests_per_minute: int):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_minute: Maximum number of requests allowed per minute.
                For example, 30 means one request every 2 seconds.
        """
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        
        self.min_delay = 60.0 / requests_per_minute
        self.last_call_time = 0.0
    
    async def acquire(self) -> None:
        """
        Acquire permission to make an API call.
        
        If called too soon after the last call, sleeps until enough time
        has elapsed to respect the rate limit.
        """
        now = time.time()
        elapsed = now - self.last_call_time
        
        if elapsed < self.min_delay:
            wait_time = self.min_delay - elapsed
            await asyncio.sleep(wait_time)
        
        self.last_call_time = time.time()
    
    def get_stats(self) -> dict[str, float]:
        """
        Get rate limiter statistics for debugging/monitoring.
        
        Returns:
            Dictionary with min_delay, last_call_time, and time_since_last_call.
        """
        return {
            "min_delay_seconds": self.min_delay,
            "last_call_time": self.last_call_time,
            "time_since_last_call": time.time() - self.last_call_time,
        }
