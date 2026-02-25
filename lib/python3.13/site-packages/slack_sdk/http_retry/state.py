from typing import Optional, Any, Dict


class RetryState:
    next_attempt_requested: bool
    current_attempt: int  # zero-origin
    custom_values: Optional[Dict[str, Any]]

    def __init__(
        self,
        *,
        current_attempt: int = 0,
        custom_values: Optional[Dict[str, Any]] = None,
    ):
        self.next_attempt_requested = False
        self.current_attempt = current_attempt
        self.custom_values = custom_values

    def increment_current_attempt(self) -> int:
        self.current_attempt += 1
        return self.current_attempt
