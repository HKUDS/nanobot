import base64
import gzip
import importlib
import io
import logging
import secrets
import zlib

from . import packet
from . import payload

default_logger = logging.getLogger('engineio.server')


class BaseServer:
    compression_methods = ['gzip', 'deflate']
    event_names = ['connect', 'disconnect', 'message']
    valid_transports = ['polling', 'websocket']
    _default_monitor_clients = True
    sequence_number = 0

    class reason:
        """Disconnection reasons."""
        #: Server-initiated disconnection.
        SERVER_DISCONNECT = 'server disconnect'
        #: Client-initiated disconnection.
        CLIENT_DISCONNECT = 'client disconnect'
        #: Ping timeout.
        PING_TIMEOUT = 'ping timeout'
        #: Transport close.
        TRANSPORT_CLOSE = 'transport close'
        #: Transport error.
        TRANSPORT_ERROR = 'transport error'

    def __init__(self, async_mode=None, ping_interval=25, ping_timeout=20,
                 max_http_buffer_size=1000000, allow_upgrades=True,
                 http_compression=True, compression_threshold=1024,
                 cookie=None, cors_allowed_origins=None,
                 cors_credentials=True, logger=False, json=None,
                 async_handlers=True, monitor_clients=None, transports=None,
                 **kwargs):
        self.ping_timeout = ping_timeout
        if isinstance(ping_interval, tuple):
            self.ping_interval = ping_interval[0]
            self.ping_interval_grace_period = ping_interval[1]
        else:
            self.ping_interval = ping_interval
            self.ping_interval_grace_period = 0
        self.max_http_buffer_size = max_http_buffer_size
        self.allow_upgrades = allow_upgrades
        self.http_compression = http_compression
        self.compression_threshold = compression_threshold
        self.cookie = cookie
        self.cors_allowed_origins = cors_allowed_origins
        self.cors_credentials = cors_credentials
        self.async_handlers = async_handlers
        self.sockets = {}
        self.handlers = {}
        self.log_message_keys = set()
        self.start_service_task = monitor_clients \
            if monitor_clients is not None else self._default_monitor_clients
        self.service_task_handle = None
        self.service_task_event = None
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
        modes = self.async_modes()
        if async_mode is not None:
            modes = [async_mode] if async_mode in modes else []
        self._async = None
        self.async_mode = None
        for mode in modes:
            try:
                self._async = importlib.import_module(
                    'engineio.async_drivers.' + mode)._async
                asyncio_based = self._async['asyncio'] \
                    if 'asyncio' in self._async else False
                if asyncio_based != self.is_asyncio_based():
                    continue  # pragma: no cover
                self.async_mode = mode
                break
            except ImportError:
                pass
        if self.async_mode is None:
            raise ValueError('Invalid async_mode specified')
        if self.is_asyncio_based() and \
                ('asyncio' not in self._async or not
                 self._async['asyncio']):  # pragma: no cover
            raise ValueError('The selected async_mode is not asyncio '
                             'compatible')
        if not self.is_asyncio_based() and 'asyncio' in self._async and \
                self._async['asyncio']:  # pragma: no cover
            raise ValueError('The selected async_mode requires asyncio and '
                             'must use the AsyncServer class')
        if transports is not None:
            if isinstance(transports, str):
                transports = [transports]
            transports = [transport for transport in transports
                          if transport in self.valid_transports]
            if not transports:
                raise ValueError('No valid transports provided')
        self.transports = transports or self.valid_transports
        self.logger.info('Server initialized for %s.', self.async_mode)

    def is_asyncio_based(self):
        return False

    def async_modes(self):
        return ['eventlet', 'gevent_uwsgi', 'gevent', 'threading']

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
            def connect_handler(sid, environ):
                print('Connection request')
                if environ['REMOTE_ADDR'] in blacklisted:
                    return False  # reject

            # as a method:
            def message_handler(sid, msg):
                print('Received message: ', msg)
                eio.send(sid, 'response')
            eio.on('message', message_handler)

        The handler function receives the ``sid`` (session ID) for the
        client as first argument. The ``'connect'`` event handler receives the
        WSGI environment as a second argument, and can return ``False`` to
        reject the connection. The ``'message'`` handler receives the message
        payload as a second argument. The ``'disconnect'`` handler does not
        take a second argument.
        """
        if event not in self.event_names:
            raise ValueError('Invalid event')

        def set_handler(handler):
            self.handlers[event] = handler
            return handler

        if handler is None:
            return set_handler
        set_handler(handler)

    def transport(self, sid):
        """Return the name of the transport used by the client.

        The two possible values returned by this function are ``'polling'``
        and ``'websocket'``.

        :param sid: The session of the client.
        """
        return 'websocket' if self._get_socket(sid).upgraded else 'polling'

    def create_queue(self, *args, **kwargs):
        """Create a queue object using the appropriate async model.

        This is a utility function that applications can use to create a queue
        without having to worry about using the correct call for the selected
        async mode.
        """
        return self._async['queue'](*args, **kwargs)

    def get_queue_empty_exception(self):
        """Return the queue empty exception for the appropriate async model.

        This is a utility function that applications can use to work with a
        queue without having to worry about using the correct call for the
        selected async mode.
        """
        return self._async['queue_empty']

    def create_event(self, *args, **kwargs):
        """Create an event object using the appropriate async model.

        This is a utility function that applications can use to create an
        event without having to worry about using the correct call for the
        selected async mode.
        """
        return self._async['event'](*args, **kwargs)

    def generate_id(self):
        """Generate a unique session id."""
        id = base64.b64encode(
            secrets.token_bytes(12) + self.sequence_number.to_bytes(3, 'big'))
        self.sequence_number = (self.sequence_number + 1) & 0xffffff
        return id.decode('utf-8').replace('/', '_').replace('+', '-')

    def _generate_sid_cookie(self, sid, attributes):
        """Generate the sid cookie."""
        cookie = attributes.get('name', 'io') + '=' + sid
        for attribute, value in attributes.items():
            if attribute == 'name':
                continue
            if callable(value):
                value = value()
            if value is True:
                cookie += '; ' + attribute
            else:
                cookie += '; ' + attribute + '=' + value
        return cookie

    def _upgrades(self, sid, transport):
        """Return the list of possible upgrades for a client connection."""
        if not self.allow_upgrades or self._get_socket(sid).upgraded or \
                transport == 'websocket':
            return []
        if self._async['websocket'] is None:  # pragma: no cover
            self._log_error_once(
                'The WebSocket transport is not available, you must install a '
                'WebSocket server that is compatible with your async mode to '
                'enable it. See the documentation for details.',
                'no-websocket')
            return []
        return ['websocket']

    def _get_socket(self, sid):
        """Return the socket object for a given session."""
        try:
            s = self.sockets[sid]
        except KeyError:
            raise KeyError('Session not found')
        if s.closed:
            del self.sockets[sid]
            raise KeyError('Session is disconnected')
        return s

    def _ok(self, packets=None, headers=None, jsonp_index=None):
        """Generate a successful HTTP response."""
        if packets is not None:
            if headers is None:
                headers = []
            headers += [('Content-Type', 'text/plain; charset=UTF-8')]
            return {'status': '200 OK',
                    'headers': headers,
                    'response': payload.Payload(packets=packets).encode(
                        jsonp_index=jsonp_index).encode('utf-8')}
        else:
            return {'status': '200 OK',
                    'headers': [('Content-Type', 'text/plain')],
                    'response': b'OK'}

    def _bad_request(self, message=None):
        """Generate a bad request HTTP error response."""
        if message is None:
            message = 'Bad Request'
        message = packet.Packet.json.dumps(message)
        return {'status': '400 BAD REQUEST',
                'headers': [('Content-Type', 'text/plain')],
                'response': message.encode('utf-8')}

    def _method_not_found(self):
        """Generate a method not found HTTP error response."""
        return {'status': '405 METHOD NOT FOUND',
                'headers': [('Content-Type', 'text/plain')],
                'response': b'Method Not Found'}

    def _unauthorized(self, message=None):
        """Generate a unauthorized HTTP error response."""
        if message is None:
            message = 'Unauthorized'
        message = packet.Packet.json.dumps(message)
        return {'status': '401 UNAUTHORIZED',
                'headers': [('Content-Type', 'application/json')],
                'response': message.encode('utf-8')}

    def _cors_allowed_origins(self, environ):
        if self.cors_allowed_origins is None:
            allowed_origins = []
            if 'wsgi.url_scheme' in environ and 'HTTP_HOST' in environ:
                allowed_origins.append('{scheme}://{host}'.format(
                    scheme=environ['wsgi.url_scheme'],
                    host=environ['HTTP_HOST']))
                if 'HTTP_X_FORWARDED_PROTO' in environ or \
                        'HTTP_X_FORWARDED_HOST' in environ:
                    scheme = environ.get(
                        'HTTP_X_FORWARDED_PROTO',
                        environ['wsgi.url_scheme']).split(',')[0].strip()
                    allowed_origins.append('{scheme}://{host}'.format(
                        scheme=scheme, host=environ.get(
                            'HTTP_X_FORWARDED_HOST',
                            environ['HTTP_HOST']).split(
                                ',')[0].strip()))
        elif self.cors_allowed_origins == '*':
            allowed_origins = None
        elif isinstance(self.cors_allowed_origins, str):
            allowed_origins = [self.cors_allowed_origins]
        elif callable(self.cors_allowed_origins):
            origin = environ.get('HTTP_ORIGIN')
            try:
                is_allowed = self.cors_allowed_origins(origin, environ)
            except TypeError:
                is_allowed = self.cors_allowed_origins(origin)
            allowed_origins = [origin] if is_allowed else []
        else:
            if '*' in self.cors_allowed_origins:
                allowed_origins = None
            else:
                allowed_origins = self.cors_allowed_origins
        return allowed_origins

    def _cors_headers(self, environ):
        """Return the cross-origin-resource-sharing headers."""
        if self.cors_allowed_origins == []:
            # special case, CORS handling is completely disabled
            return []
        headers = []
        allowed_origins = self._cors_allowed_origins(environ)
        if 'HTTP_ORIGIN' in environ and \
                (allowed_origins is None or environ['HTTP_ORIGIN'] in
                 allowed_origins):
            headers = [('Access-Control-Allow-Origin', environ['HTTP_ORIGIN'])]
        if environ['REQUEST_METHOD'] == 'OPTIONS':
            headers += [('Access-Control-Allow-Methods', 'OPTIONS, GET, POST')]
        if 'HTTP_ACCESS_CONTROL_REQUEST_HEADERS' in environ:
            headers += [('Access-Control-Allow-Headers',
                        environ['HTTP_ACCESS_CONTROL_REQUEST_HEADERS'])]
        if self.cors_credentials:
            headers += [('Access-Control-Allow-Credentials', 'true')]
        return headers

    def _gzip(self, response):
        """Apply gzip compression to a response."""
        bytesio = io.BytesIO()
        with gzip.GzipFile(fileobj=bytesio, mode='w') as gz:
            gz.write(response)
        return bytesio.getvalue()

    def _deflate(self, response):
        """Apply deflate compression to a response."""
        return zlib.compress(response)

    def _log_error_once(self, message, message_key):
        """Log message with logging.ERROR level the first time, then log
        with given level."""
        if message_key not in self.log_message_keys:
            self.logger.error(message + ' (further occurrences of this error '
                              'will be logged with level INFO)')
            self.log_message_keys.add(message_key)
        else:
            self.logger.info(message)
