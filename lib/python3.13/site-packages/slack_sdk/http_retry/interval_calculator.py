class RetryIntervalCalculator:
    """Retry interval calculator interface."""

    def calculate_sleep_duration(self, current_attempt: int) -> float:
        """Calculates an interval duration in seconds.

        Args:
            current_attempt: the number of the current attempt (zero-origin; 0 means no retries are done so far)
        Returns:
            calculated interval duration in seconds
        """
        raise NotImplementedError()
