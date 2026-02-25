from datetime import timedelta
from functools import wraps

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.util import maybe_ref

try:
    from tornado.ioloop import IOLoop
except ImportError as exc:  # pragma: nocover
    raise ImportError("TornadoScheduler requires tornado installed") from exc


def run_in_ioloop(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if self._ioloop is None:
            raise SchedulerNotRunningError

        self._ioloop.add_callback(func, self, *args, **kwargs)

    return wrapper


class TornadoScheduler(BaseScheduler):
    """
    A scheduler that runs on a Tornado IOLoop.

    The default executor can run jobs based on native coroutines (``async def``).

    =========== ===============================================================
    ``io_loop`` Tornado IOLoop instance to use (defaults to the global IO loop)
    =========== ===============================================================
    """

    _ioloop = None
    _timeout = None

    @run_in_ioloop
    def _shutdown(self, wait=True):
        super().shutdown(wait)
        self._stop_timer()

    def shutdown(self, wait=True):
        if not self.running:
            raise SchedulerNotRunningError

        self._shutdown(wait)

    def _configure(self, config):
        self._ioloop = maybe_ref(config.pop("io_loop", None)) or IOLoop.current()
        super()._configure(config)

    def _start_timer(self, wait_seconds):
        self._stop_timer()
        if wait_seconds is not None:
            self._timeout = self._ioloop.add_timeout(
                timedelta(seconds=wait_seconds), self.wakeup
            )

    def _stop_timer(self):
        if self._timeout:
            self._ioloop.remove_timeout(self._timeout)
            del self._timeout

    def _create_default_executor(self):
        from apscheduler.executors.tornado import TornadoExecutor

        return TornadoExecutor()

    @run_in_ioloop
    def wakeup(self):
        self._stop_timer()
        wait_seconds = self._process_jobs()
        self._start_timer(wait_seconds)
