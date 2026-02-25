import logging
import signal
import threading
import time
import urllib
from . import packet

default_logger = logging.getLogger('engineio.client')
connected_clients = []


def signal_handler(sig, frame):
    """SIGINT handler.

    Disconnect all active clients and then invoke the original signal handler.
    """
    for client in connected_clients[:]:
        if not client.is_asyncio_based():
            client.disconnect()
    if callable(original_signal_handler):
        return original_signal_handler(sig, frame)
    else:  # pragma: no cover
        # Handle case where no original SIGINT handler was present.
        return signal.default_int_handler(sig, frame)


original_signal_handler = None


class BaseClient:
    event_names = ['connect', 'disconnect', 'message']

    class reason:
        """Disconnection reasons."""
        #: Client-initiated disconnection.
        CLIENT_DISCONNECT = 'client disconnect'
        #: Server-initiated disconnection.
        SERVER_DISCONNECT = 'server disconnect'
        #: Transport error.
        TRANSPORT_ERROR = 'transport error'

    def __init__(self, logger=False, json=None, request_timeout=5,
                 http_session=None, ssl_verify=True, handle_sigint=True,
                 websocket_extra_options=None, timestamp_requests=True):
        global original_signal_handler
        if handle_sigint and original_signal_handler is None and \
                threading.current_thread() == threading.main_thread():
            original_signal_handler = signal.signal(signal.SIGINT,
                                                    signal_handler)
        self.handlers = {}
        self.base_url = None
        self.transports = None
        self.current_transport = None
        self.sid = None
        self.upgrades = None
        self.ping_interval = None
        self.ping_timeout = None
        self.http = http_session
        self.external_http = http_session is not None
        self.handle_sigint = handle_sigint
        self.ws = None
        self.read_loop_task = None
        self.write_loop_task = None
        self.queue = self.create_queue()
        self.queue_empty = self.get_queue_empty_exception()
        self.state = 'disconnected'
        self.ssl_verify = ssl_verify
        self.websocket_extra_options = websocket_extra_options or {}
        self.timestamp_requests = timestamp_requests

        if json is not None:
            packet.Packet.json = json
        if not isinstance(logger, bool):
            self.logger = logger
        else:
            self.logger = default_logger
            if self.logger.level == logging.NOTSET:
                if logger:
                    self.logger.setLevel(logging.INFO)
                else:
                    self.logger.setLevel(logging.ERROR)
                self.logger.addHandler(logging.StreamHandler())

        self.request_timeout = request_timeout

    def is_asyncio_based(self):
        return False

    def on(self, event, handler=None):
        """Register an event handler.

        :param event: The event name. Can be ``'connect'``, ``'message'`` or
                      ``'disconnect'``.
        :param handler: The function that should be invoked to handle the
                        event. When this parameter is not given, the method
                        acts as a decorator for the handler function.

        Example usage::

            # as a decorator:
            @eio.on('connect')
            def connect_handler():
                print('Connection request')

            # as a method:
            def message_handler(msg):
                print('Received message: ', msg)
                eio.send('response')
            eio.on('message', message_handler)
        """
        if event not in self.event_names:
            raise ValueError('Invalid event')

        def set_handler(handler):
            self.handlers[event] = handler
            return handler

        if handler is None:
            return set_handler
        set_handler(handler)

    def transport(self):
        """Return the name of the transport currently in use.

        The possible values returned by this function are ``'polling'`` and
        ``'websocket'``.
        """
        return self.current_transport

    def _reset(self):
        self.state = 'disconnected'
        self.sid = None

    def _get_engineio_url(self, url, engineio_path, transport):
        """Generate the Engine.IO connection URL."""
        engineio_path = engineio_path.strip('/')
        parsed_url = urllib.parse.urlparse(url)

        if transport == 'polling':
            scheme = 'http'
        elif transport == 'websocket':
            scheme = 'ws'
        else:  # pragma: no cover
            raise ValueError('invalid transport')
        if parsed_url.scheme in ['https', 'wss']:
            scheme += 's'

        return ('{scheme}://{netloc}/{path}/?{query}'
                '{sep}transport={transport}&EIO=4').format(
                    scheme=scheme, netloc=parsed_url.netloc,
                    path=engineio_path, query=parsed_url.query,
                    sep='&' if parsed_url.query else '',
                    transport=transport)

    def _get_url_timestamp(self):
        """Generate the Engine.IO query string timestamp."""
        if not self.timestamp_requests:
            return ''
        return '&t=' + str(time.time())

    def create_queue(self, *args, **kwargs):  # pragma: no cover
        """Create a queue object."""
        raise NotImplementedError('must be implemented in a subclass')

    def get_queue_empty_exception(self):  # pragma: no cover
        """Return the queue empty exception raised by queues created by the
        ``create_queue()`` method.
        """
        raise NotImplementedError('must be implemented in a subclass')
