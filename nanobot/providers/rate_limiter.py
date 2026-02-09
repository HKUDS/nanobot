"""Rate limiter for controlling API call frequency."""

import asyncio
import time
from collections import deque


class RateLimiter:
    """
    Burst-aware rate limiter for APIs with rolling window limits.
    
    Handles providers like NVIDIA free tier that enforce:
    - Maximum N requests per rolling window (e.g., 4 calls per 60 seconds)
    - Regardless of spacing between individual calls
    
    Example:
        >>> # NVIDIA free tier: max 4 calls per 60 seconds
        >>> limiter = RateLimiter(burst_size=4, window_seconds=60)
        >>> for i in range(10):
        ...     await limiter.acquire()  # First 4 are immediate, then waits ~60s
    """
    
    def __init__(
        self, 
        burst_size: int = 4, 
        window_seconds: float = 60.0,
        min_delay_seconds: float = 0.0,
    ):
        """
        Initialize burst-aware rate limiter.
        
        Args:
            burst_size: Maximum number of requests allowed per window.
            window_seconds: Duration of the rolling window in seconds.
            min_delay_seconds: Optional minimum delay between consecutive calls
                (useful for providers that also have per-second limits).
        """
        if burst_size <= 0:
            raise ValueError("burst_size must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if min_delay_seconds < 0:
            raise ValueError("min_delay_seconds cannot be negative")
        
        self.burst_size = burst_size
        self.window_seconds = window_seconds
        self.min_delay_seconds = min_delay_seconds
        
        # Track timestamps of recent calls
        self.call_history: deque[float] = deque(maxlen=burst_size)
        self.last_call_time = 0.0
    
    async def acquire(self) -> None:
        """
        Acquire permission to make an API call.
        
        Respects both burst limits and minimum spacing:
        1. Enforces minimum delay between consecutive calls (if configured)
        2. Checks if we're within burst limit for the rolling window
        3. If burst exhausted, waits until oldest call expires from window
        """
        now = time.time()
        
        # Step 1: Enforce minimum delay between calls (if configured)
        if self.min_delay_seconds > 0:
            elapsed_since_last = now - self.last_call_time
            if elapsed_since_last < self.min_delay_seconds:
                wait_time = self.min_delay_seconds - elapsed_since_last
                await asyncio.sleep(wait_time)
                now = time.time()
        
        # Step 2: Check burst limit
        # Remove calls that are outside the rolling window
        cutoff_time = now - self.window_seconds
        while self.call_history and self.call_history[0] < cutoff_time:
            self.call_history.popleft()
        
        # Step 3: Wait if we've hit the burst limit
        if len(self.call_history) >= self.burst_size:
            # Calculate how long until the oldest call expires
            oldest_call = self.call_history[0]
            time_until_reset = (oldest_call + self.window_seconds) - now
            
            if time_until_reset > 0:
                print(f"⏸️  Rate limit: burst exhausted ({self.burst_size} calls in {self.window_seconds}s window)")
                print(f"   Waiting {time_until_reset:.1f}s until window resets...")
                await asyncio.sleep(time_until_reset)
                now = time.time()
                
                # Clean up expired calls after wait
                cutoff_time = now - self.window_seconds
                while self.call_history and self.call_history[0] < cutoff_time:
                    self.call_history.popleft()
        
        # Record this call
        self.call_history.append(now)
        self.last_call_time = now
    
    def get_stats(self) -> dict[str, any]:
        """
        Get rate limiter statistics for debugging/monitoring.
        
        Returns:
            Dictionary with configuration, current window usage, and timing info.
        """
        now = time.time()
        cutoff_time = now - self.window_seconds
        
        # Count valid calls in current window
        valid_calls = sum(1 for t in self.call_history if t >= cutoff_time)
        
        # Calculate time until next available slot
        time_until_next_slot = 0.0
        if len(self.call_history) >= self.burst_size:
            oldest_call = self.call_history[0]
            time_until_next_slot = max(0, (oldest_call + self.window_seconds) - now)
        
        return {
            "burst_size": self.burst_size,
            "window_seconds": self.window_seconds,
            "min_delay_seconds": self.min_delay_seconds,
            "calls_in_current_window": valid_calls,
            "slots_available": max(0, self.burst_size - valid_calls),
            "time_until_next_slot_seconds": time_until_next_slot,
            "last_call_time": self.last_call_time,
            "time_since_last_call_seconds": now - self.last_call_time if self.last_call_time > 0 else float('inf'),
        }
