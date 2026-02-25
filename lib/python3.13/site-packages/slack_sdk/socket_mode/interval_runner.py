import threading
from threading import Thread, Event
from typing import Callable


class IntervalRunner:
    event: Event
    thread: Thread

    def __init__(self, target: Callable[[], None], interval_seconds: float = 0.1):
        self.event = threading.Event()
        self.target = target
        self.interval_seconds = interval_seconds
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True

    def _run(self) -> None:
        while not self.event.is_set():
            self.target()
            self.event.wait(self.interval_seconds)

    def start(self) -> "IntervalRunner":
        self.thread.start()
        return self

    def is_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def shutdown(self):
        if self.is_alive():
            self.event.set()
            self.thread.join()
        self.thread = None
