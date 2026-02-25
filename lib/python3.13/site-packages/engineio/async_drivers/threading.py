import queue
import threading
import time
from engineio.async_drivers._websocket_wsgi import SimpleWebSocketWSGI


class DaemonThread(threading.Thread):  # pragma: no cover
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, daemon=True)


_async = {
    'thread': DaemonThread,
    'queue': queue.Queue,
    'queue_empty': queue.Empty,
    'event': threading.Event,
    'websocket': SimpleWebSocketWSGI,
    'sleep': time.sleep,
}
