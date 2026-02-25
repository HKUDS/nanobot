import gevent
from gevent import queue
from gevent.event import Event
try:
    # use gevent-websocket if installed
    import geventwebsocket  # noqa
    SimpleWebSocketWSGI = None
except ImportError:  # pragma: no cover
    # fallback to simple_websocket when gevent-websocket is not installed
    from engineio.async_drivers._websocket_wsgi import SimpleWebSocketWSGI


class Thread(gevent.Greenlet):  # pragma: no cover
    """
    This wrapper class provides gevent Greenlet interface that is compatible
    with the standard library's Thread class.
    """
    def __init__(self, target, args=[], kwargs={}):
        super().__init__(target, *args, **kwargs)

    def _run(self):
        return self.run()


if SimpleWebSocketWSGI is not None:
    class WebSocketWSGI(SimpleWebSocketWSGI):  # pragma: no cover
        """
        This wrapper class provides a gevent WebSocket interface that is
        compatible with eventlet's implementation, using the simple-websocket
        package.
        """
        def __init__(self, handler, server):
            # to avoid the requirement that the standard library is
            # monkey-patched, here we pass the gevent versions of the
            # concurrency and networking classes required by simple-websocket
            import gevent.event
            import gevent.selectors
            super().__init__(handler, server,
                             thread_class=Thread,
                             event_class=gevent.event.Event,
                             selector_class=gevent.selectors.DefaultSelector)
else:
    class WebSocketWSGI:  # pragma: no cover
        """
        This wrapper class provides a gevent WebSocket interface that is
        compatible with eventlet's implementation, using the gevent-websocket
        package.
        """
        def __init__(self, handler, server):
            self.app = handler

        def __call__(self, environ, start_response):
            if 'wsgi.websocket' not in environ:
                raise RuntimeError('The gevent-websocket server is not '
                                   'configured appropriately. '
                                   'See the Deployment section of the '
                                   'documentation for more information.')
            self._sock = environ['wsgi.websocket']
            self.environ = environ
            self.version = self._sock.version
            self.path = self._sock.path
            self.origin = self._sock.origin
            self.protocol = self._sock.protocol
            return self.app(self)

        def close(self):
            return self._sock.close()

        def send(self, message):
            return self._sock.send(message)

        def wait(self):
            return self._sock.receive()


_async = {
    'thread': Thread,
    'queue': queue.JoinableQueue,
    'queue_empty': queue.Empty,
    'event': Event,
    'websocket': WebSocketWSGI,
    'sleep': gevent.sleep,
}
