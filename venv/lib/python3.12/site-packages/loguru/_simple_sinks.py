import inspect
import logging
import weakref

from ._asyncio_loop import get_running_loop, get_task_loop


class StreamSink:
    def __init__(self, stream):
        self._stream = stream
        self._flushable = callable(getattr(stream, "flush", None))
        self._stoppable = callable(getattr(stream, "stop", None))
        self._completable = inspect.iscoroutinefunction(getattr(stream, "complete", None))

    def write(self, message):
        self._stream.write(message)
        if self._flushable:
            self._stream.flush()

    def stop(self):
        if self._stoppable:
            self._stream.stop()

    def tasks_to_complete(self):
        if not self._completable:
            return []
        return [self._stream.complete()]


class StandardSink:
    def __init__(self, handler):
        self._handler = handler

    def write(self, message):
        raw_record = message.record
        message = str(message)
        exc = raw_record["exception"]
        record = logging.getLogger().makeRecord(
            raw_record["name"],
            raw_record["level"].no,
            raw_record["file"].path,
            raw_record["line"],
            message,
            (),
            (exc.type, exc.value, exc.traceback) if exc else None,
            raw_record["function"],
            {"extra": raw_record["extra"]},
        )
        if exc:
            record.exc_text = "\n"
        record.levelname = raw_record["level"].name
        self._handler.handle(record)

    def stop(self):
        self._handler.close()

    def tasks_to_complete(self):
        return []


class AsyncSink:
    def __init__(self, function, loop, error_interceptor):
        self._function = function
        self._loop = loop
        self._error_interceptor = error_interceptor
        self._tasks = weakref.WeakSet()

    def write(self, message):
        try:
            loop = self._loop or get_running_loop()
        except RuntimeError:
            return

        coroutine = self._function(message)
        task = loop.create_task(coroutine)

        def check_exception(future):
            if future.cancelled() or future.exception() is None:
                return
            if not self._error_interceptor.should_catch():
                raise future.exception()
            self._error_interceptor.print(message.record, exception=future.exception())

        task.add_done_callback(check_exception)
        self._tasks.add(task)

    def stop(self):
        for task in self._tasks:
            task.cancel()

    def tasks_to_complete(self):
        # To avoid errors due to "self._tasks" being mutated while iterated, the
        # "tasks_to_complete()" method must be protected by the same lock as "write()" (which
        # happens to be the handler lock). However, the tasks must not be awaited while the lock is
        # acquired as this could lead to a deadlock. Therefore, we first need to collect the tasks
        # to complete, then return them so that they can be awaited outside of the lock.
        return [self._complete_task(task) for task in self._tasks]

    async def _complete_task(self, task):
        loop = get_running_loop()
        if get_task_loop(task) is not loop:
            return
        try:
            await task
        except Exception:
            pass  # Handled in "check_exception()"

    def __getstate__(self):
        state = self.__dict__.copy()
        state["_tasks"] = None
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._tasks = weakref.WeakSet()


class CallableSink:
    def __init__(self, function):
        self._function = function

    def write(self, message):
        self._function(message)

    def stop(self):
        pass

    def tasks_to_complete(self):
        return []
