import random


class Jitter:
    """Jitter interface"""

    def recalculate(self, duration: float) -> float:
        """Recalculate the given duration.
        see also: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/

        Args:
            duration: the duration in seconds

        Returns:
            A new duration that the jitter amount is added
        """
        raise NotImplementedError()


class RandomJitter(Jitter):
    """Random jitter implementation"""

    def recalculate(self, duration: float) -> float:
        return duration + random.random()
