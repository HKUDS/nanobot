from threading import TIMEOUT_MAX, Event

from apscheduler.schedulers.base import STATE_STOPPED, BaseScheduler


class BlockingScheduler(BaseScheduler):
    """
    A scheduler that runs in the foreground
    (:meth:`~apscheduler.schedulers.base.BaseScheduler.start` will block).
    """

    _event = None

    def start(self, *args, **kwargs):
        if self._event is None or self._event.is_set():
            self._event = Event()

        super().start(*args, **kwargs)
        self._main_loop()

    def shutdown(self, wait=True):
        super().shutdown(wait)
        self._event.set()

    def _main_loop(self):
        wait_seconds = TIMEOUT_MAX
        while self.state != STATE_STOPPED:
            self._event.wait(wait_seconds)
            self._event.clear()
            wait_seconds = self._process_jobs()

    def wakeup(self):
        self._event.set()
