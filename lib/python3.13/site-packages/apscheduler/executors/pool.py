import concurrent.futures
import multiprocessing
from abc import abstractmethod
from concurrent.futures.process import BrokenProcessPool

from apscheduler.executors.base import BaseExecutor, run_job


class BasePoolExecutor(BaseExecutor):
    @abstractmethod
    def __init__(self, pool):
        super().__init__()
        self._pool = pool

    def _do_submit_job(self, job, run_times):
        def callback(f):
            exc, tb = (
                f.exception_info()
                if hasattr(f, "exception_info")
                else (f.exception(), getattr(f.exception(), "__traceback__", None))
            )
            if exc:
                self._run_job_error(job.id, exc, tb)
            else:
                self._run_job_success(job.id, f.result())

        f = self._pool.submit(
            run_job, job, job._jobstore_alias, run_times, self._logger.name
        )
        f.add_done_callback(callback)

    def shutdown(self, wait=True):
        self._pool.shutdown(wait)


class ThreadPoolExecutor(BasePoolExecutor):
    """
    An executor that runs jobs in a concurrent.futures thread pool.

    Plugin alias: ``threadpool``

    :param max_workers: the maximum number of spawned threads.
    :param pool_kwargs: dict of keyword arguments to pass to the underlying
        ThreadPoolExecutor constructor
    """

    def __init__(self, max_workers=10, pool_kwargs=None):
        pool_kwargs = pool_kwargs or {}
        pool = concurrent.futures.ThreadPoolExecutor(int(max_workers), **pool_kwargs)
        super().__init__(pool)


class ProcessPoolExecutor(BasePoolExecutor):
    """
    An executor that runs jobs in a concurrent.futures process pool.

    Plugin alias: ``processpool``

    :param max_workers: the maximum number of spawned processes.
    :param pool_kwargs: dict of keyword arguments to pass to the underlying
        ProcessPoolExecutor constructor
    """

    def __init__(self, max_workers=10, pool_kwargs=None):
        self.pool_kwargs = pool_kwargs or {}
        self.pool_kwargs.setdefault("mp_context", multiprocessing.get_context("spawn"))
        pool = concurrent.futures.ProcessPoolExecutor(
            int(max_workers), **self.pool_kwargs
        )
        super().__init__(pool)

    def _do_submit_job(self, job, run_times):
        try:
            super()._do_submit_job(job, run_times)
        except BrokenProcessPool:
            self._logger.warning(
                "Process pool is broken; replacing pool with a fresh instance"
            )
            self._pool = self._pool.__class__(
                self._pool._max_workers, **self.pool_kwargs
            )
            super()._do_submit_job(job, run_times)
