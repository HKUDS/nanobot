import gevent
from gevent import queue
from gevent.event import Event
from gevent import selectors
import uwsgi
_websocket_available = hasattr(uwsgi, 'websocket_handshake')


class Thread(gevent.Greenlet):  # pragma: no cover
    """
    This wrapper class provides gevent Greenlet interface that is compatible
    with the standard library's Thread class.
    """
    def __init__(self, target, args=[], kwargs={}):
        super().__init__(target, *args, **kwargs)

    def _run(self):
        return self.run()


class uWSGIWebSocket:  # pragma: no cover
    """
    This wrapper class provides a uWSGI WebSocket interface that is
    compatible with eventlet's implementation.
    """
    def __init__(self, handler, server):
        self.app = handler
        self._sock = None
        self.received_messages = []

    def __call__(self, environ, start_response):
        self._sock = uwsgi.connection_fd()
        self.environ = environ

        uwsgi.websocket_handshake()

        self._req_ctx = None
        if hasattr(uwsgi, 'request_context'):
            # uWSGI >= 2.1.x with support for api access across-greenlets
            self._req_ctx = uwsgi.request_context()
        else:
            # use event and queue for sending messages
            self._event = Event()
            self._send_queue = queue.Queue()

            # spawn a select greenlet
            def select_greenlet_runner(fd, event):
                """Sets event when data becomes available to read on fd."""
                sel = selectors.DefaultSelector()
                sel.register(fd, selectors.EVENT_READ)
                try:
                    while True:
                        sel.select()
                        event.set()
                except gevent.GreenletExit:
                    sel.unregister(fd)
            self._select_greenlet = gevent.spawn(
                select_greenlet_runner,
                self._sock,
                self._event)

        self.app(self)
        uwsgi.disconnect()
        return ''  # send nothing as response

    def close(self):
        """Disconnects uWSGI from the client."""
        if self._req_ctx is None:
            # better kill it here in case wait() is not called again
            self._select_greenlet.kill()
            self._event.set()

    def _send(self, msg):
        """Transmits message either in binary or UTF-8 text mode,
        depending on its type."""
        if isinstance(msg, bytes):
            method = uwsgi.websocket_send_binary
        else:
            method = uwsgi.websocket_send
        if self._req_ctx is not None:
            method(msg, request_context=self._req_ctx)
        else:
            method(msg)

    def _decode_received(self, msg):
        """Returns either bytes or str, depending on message type."""
        if not isinstance(msg, bytes):
            # already decoded - do nothing
            return msg
        # only decode from utf-8 if message is not binary data
        type = ord(msg[0:1])
        if type >= 48:  # no binary
            return msg.decode('utf-8')
        # binary message, don't try to decode
        return msg

    def send(self, msg):
        """Queues a message for sending. Real transmission is done in
        wait method.
        Sends directly if uWSGI version is new enough."""
        if self._req_ctx is not None:
            self._send(msg)
        else:
            self._send_queue.put(msg)
            self._event.set()

    def wait(self):
        """Waits and returns received messages.
        If running in compatibility mode for older uWSGI versions,
        it also sends messages that have been queued by send().
        A return value of None means that connection was closed.
        This must be called repeatedly. For uWSGI < 2.1.x it must
        be called from the main greenlet."""
        while True:
            if self._req_ctx is not None:
                try:
                    msg = uwsgi.websocket_recv(request_context=self._req_ctx)
                except OSError:  # connection closed
                    self.close()
                    return None
                return self._decode_received(msg)
            else:
                if self.received_messages:
                    return self.received_messages.pop(0)

                # we wake up at least every 3 seconds to let uWSGI
                # do its ping/ponging
                event_set = self._event.wait(timeout=3)
                if event_set:
                    self._event.clear()
                    # maybe there is something to send
                    msgs = []
                    while True:
                        try:
                            msgs.append(self._send_queue.get(block=False))
                        except gevent.queue.Empty:
                            break
                    for msg in msgs:
                        try:
                            self._send(msg)
                        except OSError:
                            self.close()
                            return None
                # maybe there is something to receive, if not, at least
                # ensure uWSGI does its ping/ponging
                while True:
                    try:
                        msg = uwsgi.websocket_recv_nb()
                    except OSError:  # connection closed
                        self.close()
                        return None
                    if msg:  # message available
                        self.received_messages.append(
                            self._decode_received(msg))
                    else:
                        break
                if self.received_messages:
                    return self.received_messages.pop(0)


_async = {
    'thread': Thread,
    'queue': queue.JoinableQueue,
    'queue_empty': queue.Empty,
    'event': Event,
    'websocket': uWSGIWebSocket if _websocket_available else None,
    'sleep': gevent.sleep,
}
