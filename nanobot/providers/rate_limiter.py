"""Rate limiter for controlling API call frequency."""

import asyncio
import fcntl
import json
import os
import tempfile
import time
from collections import deque
from pathlib import Path


class RateLimiter:
    """
    Burst-aware rate limiter for APIs with rolling window limits.
    
    Handles providers like NVIDIA free tier that enforce:
    - Maximum N requests per rolling window (e.g., 4 calls per 60 seconds)
    - Regardless of spacing between individual calls
    
    State is persisted per-provider to avoid cross-provider clobbering,
    using atomic writes and file locking for crash safety and concurrency.
    
    Example:
        >>> # NVIDIA free tier: max 4 calls per 60 seconds
        >>> limiter = RateLimiter(burst_size=4, window_seconds=60, provider="nvidia")
        >>> for i in range(10):
        ...     await limiter.acquire()  # First 4 are immediate, then waits ~60s
    """
    
    def __init__(
        self, 
        burst_size: int = 4, 
        window_seconds: float = 60.0,
        min_delay_seconds: float = 0.0,
        provider: str | None = None,
        state_file: str | None = None,
    ):
        """
        Initialize burst-aware rate limiter with persistent state.
        
        Args:
            burst_size: Maximum number of requests allowed per window.
            window_seconds: Duration of the rolling window in seconds.
            min_delay_seconds: Optional minimum delay between consecutive calls.
            provider: Provider name for state isolation. Each provider gets its own
                state file to prevent cross-provider interference.
            state_file: Explicit path to state file (overrides provider-based naming).
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
        self.provider = provider
        
        # Set up persistent state file (provider-isolated)
        if state_file is not None:
            self.state_file = Path(state_file)
        else:
            state_dir = Path.home() / ".nanobot"
            state_dir.mkdir(exist_ok=True)
            if provider:
                safe_name = provider.replace("/", "_").replace("\\", "_")
                self.state_file = state_dir / f"rate_limiter_state_{safe_name}.json"
            else:
                self.state_file = state_dir / "rate_limiter_state.json"
        
        # Load state from disk (or initialize fresh)
        state = self._load_state()
        self.call_history: deque[float] = deque(state.get('call_history', []), maxlen=burst_size)
        self.last_call_time = state.get('last_call_time', 0.0)
    
    def _load_state(self) -> dict:
        """Load rate limiter state from persistent storage with file locking."""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    try:
                        return json.load(f)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        return {}
    
    def _save_state(self) -> None:
        """Save rate limiter state atomically with file locking.
        
        Uses temp-file-then-rename for crash safety: if the process is
        killed mid-write, the original state file remains intact.
        Uses fcntl.flock() to prevent concurrent CLI processes from
        clobbering each other's writes.
        """
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'call_history': list(self.call_history),
                'last_call_time': self.last_call_time,
            }
            
            # Write to temp file in same directory, then atomic rename
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.state_file.parent),
                prefix='.rate_limiter_',
                suffix='.tmp',
            )
            try:
                with os.fdopen(fd, 'w') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        json.dump(state, f)
                        f.flush()
                        os.fsync(f.fileno())
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                os.rename(tmp_path, str(self.state_file))
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            pass  # Rate limiting still works in-process
    
    async def acquire(self) -> None:
        """
        Acquire permission to make an API call.
        
        Reloads state from disk to pick up writes from other processes,
        then enforces both burst limits and minimum spacing.
        """
        # Reload state from disk to see other processes' calls
        state = self._load_state()
        if state:
            self.call_history = deque(state.get('call_history', []), maxlen=self.burst_size)
            self.last_call_time = state.get('last_call_time', 0.0)
        
        now = time.time()
        
        # Step 1: Enforce minimum delay between calls (if configured)
        if self.min_delay_seconds > 0:
            elapsed_since_last = now - self.last_call_time
            if elapsed_since_last < self.min_delay_seconds:
                wait_time = self.min_delay_seconds - elapsed_since_last
                await asyncio.sleep(wait_time)
                now = time.time()
        
        # Step 2: Remove calls outside the rolling window
        cutoff_time = now - self.window_seconds
        while self.call_history and self.call_history[0] < cutoff_time:
            self.call_history.popleft()
        
        # Step 3: Wait if we've hit the burst limit
        if len(self.call_history) >= self.burst_size:
            oldest_call = self.call_history[0]
            time_until_reset = (oldest_call + self.window_seconds) - now
            
            if time_until_reset > 0:
                print(f"⏸️  Rate limit: burst exhausted ({self.burst_size} calls in {self.window_seconds}s window)")
                print(f"   Waiting {time_until_reset:.1f}s until window resets...")
                await asyncio.sleep(time_until_reset)
                now = time.time()
                
                cutoff_time = now - self.window_seconds
                while self.call_history and self.call_history[0] < cutoff_time:
                    self.call_history.popleft()
        
        # Record this call and persist state
        self.call_history.append(now)
        self.last_call_time = now
        self._save_state()
    
    def get_stats(self) -> dict[str, any]:
        """Get rate limiter statistics for debugging/monitoring."""
        now = time.time()
        cutoff_time = now - self.window_seconds
        
        valid_calls = sum(1 for t in self.call_history if t >= cutoff_time)
        
        time_until_next_slot = 0.0
        if len(self.call_history) >= self.burst_size:
            oldest_call = self.call_history[0]
            time_until_next_slot = max(0, (oldest_call + self.window_seconds) - now)
        
        return {
            "burst_size": self.burst_size,
            "window_seconds": self.window_seconds,
            "min_delay_seconds": self.min_delay_seconds,
            "provider": self.provider,
            "calls_in_current_window": valid_calls,
            "slots_available": max(0, self.burst_size - valid_calls),
            "time_until_next_slot_seconds": time_until_next_slot,
            "last_call_time": self.last_call_time,
            "time_since_last_call_seconds": now - self.last_call_time if self.last_call_time > 0 else float('inf'),
        }
