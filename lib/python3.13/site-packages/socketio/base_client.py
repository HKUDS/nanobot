import itertools
import logging
import signal
import threading

import engineio

from . import base_namespace
from . import packet

default_logger = logging.getLogger('socketio.client')
reconnecting_clients = []


def signal_handler(sig, frame):  # pragma: no cover
    """SIGINT handler.

    Notify any clients that are in a reconnect loop to abort. Other
    disconnection tasks are handled at the engine.io level.
    """
    for client in reconnecting_clients[:]:
        client._reconnect_abort.set()
    if callable(original_signal_handler):
        return original_signal_handler(sig, frame)
    else:  # pragma: no cover
        # Handle case where no original SIGINT handler was present.
        return signal.default_int_handler(sig, frame)


original_signal_handler = None


class BaseClient:
    reserved_events = ['connect', 'connect_error', 'disconnect',
                       '__disconnect_final']
    reason = engineio.Client.reason

    def __init__(self, reconnection=True, reconnection_attempts=0,
                 reconnection_delay=1, reconnection_delay_max=5,
                 randomization_factor=0.5, logger=False, serializer='default',
                 json=None, handle_sigint=True, **kwargs):
        global original_signal_handler
        if handle_sigint and original_signal_handler is None and \
                threading.current_thread() == threading.main_thread():
            original_signal_handler = signal.signal(signal.SIGINT,
                                                    signal_handler)
        self.reconnection = reconnection
        self.reconnection_attempts = reconnection_attempts
        self.reconnection_delay = reconnection_delay
        self.reconnection_delay_max = reconnection_delay_max
        self.randomization_factor = randomization_factor
        self.handle_sigint = handle_sigint

        engineio_options = kwargs
        engineio_options['handle_sigint'] = handle_sigint
        engineio_logger = engineio_options.pop('engineio_logger', None)
        if engineio_logger is not None:
            engineio_options['logger'] = engineio_logger
        if serializer == 'default':
            self.packet_class = packet.Packet
        elif serializer == 'msgpack':
            from . import msgpack_packet
            self.packet_class = msgpack_packet.MsgPackPacket
        else:
            self.packet_class = serializer
        if json is not None:
            self.packet_class.json = json
            engineio_options['json'] = json

        self.eio = self._engineio_client_class()(**engineio_options)
        self.eio.on('connect', self._handle_eio_connect)
        self.eio.on('message', self._handle_eio_message)
        self.eio.on('disconnect', self._handle_eio_disconnect)

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

        self.connection_url = None
        self.connection_headers = None
        self.connection_auth = None
        self.connection_transports = None
        self.connection_namespaces = []
        self.socketio_path = None
        self.sid = None

        self.connected = False  #: Indicates if the client is connected or not.
        self.namespaces = {}  #: set of connected namespaces.
        self.failed_namespaces = []
        self.handlers = {}
        self.namespace_handlers = {}
        self.callbacks = {}
        self._binary_packet = None
        self._connect_event = None
        self._reconnect_task = None
        self._reconnect_abort = None

    def is_asyncio_based(self):
        return False

    def on(self, event, handler=None, namespace=None):
        """Register an event handler.

        :param event: The event name. It can be any string. The event names
                      ``'connect'``, ``'message'`` and ``'disconnect'`` are
                      reserved and should not be used. The ``'*'`` event name
                      can be used to define a catch-all event handler.
        :param handler: The function that should be invoked to handle the
                        event. When this parameter is not given, the method
                        acts as a decorator for the handler function.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the handler is associated with
                          the default namespace. A catch-all namespace can be
                          defined by passing ``'*'`` as the namespace.

        Example usage::

            # as a decorator:
            @sio.on('connect')
            def connect_handler():
                print('Connected!')

            # as a method:
            def message_handler(msg):
                print('Received message: ', msg)
                sio.send( 'response')
            sio.on('message', message_handler)

        The arguments passed to the handler function depend on the event type:

        - The ``'connect'`` event handler does not take arguments.
        - The ``'disconnect'`` event handler does not take arguments.
        - The ``'message'`` handler and handlers for custom event names receive
          the message payload as only argument. Any values returned from a
          message handler will be passed to the client's acknowledgement
          callback function if it exists.
        - A catch-all event handler receives the event name as first argument,
          followed by any arguments specific to the event.
        - A catch-all namespace event handler receives the namespace as first
          argument, followed by any arguments specific to the event.
        - A combined catch-all namespace and catch-all event handler receives
          the event name as first argument and the namespace as second
          argument, followed by any arguments specific to the event.
        """
        namespace = namespace or '/'

        def set_handler(handler):
            if namespace not in self.handlers:
                self.handlers[namespace] = {}
            self.handlers[namespace][event] = handler
            return handler

        if handler is None:
            return set_handler
        set_handler(handler)

    def event(self, *args, **kwargs):
        """Decorator to register an event handler.

        This is a simplified version of the ``on()`` method that takes the
        event name from the decorated function.

        Example usage::

            @sio.event
            def my_event(data):
                print('Received data: ', data)

        The above example is equivalent to::

            @sio.on('my_event')
            def my_event(data):
                print('Received data: ', data)

        A custom namespace can be given as an argument to the decorator::

            @sio.event(namespace='/test')
            def my_event(data):
                print('Received data: ', data)
        """
        if len(args) == 1 and len(kwargs) == 0 and callable(args[0]):
            # the decorator was invoked without arguments
            # args[0] is the decorated function
            return self.on(args[0].__name__)(args[0])
        else:
            # the decorator was invoked with arguments
            def set_handler(handler):
                return self.on(handler.__name__, *args, **kwargs)(handler)

            return set_handler

    def register_namespace(self, namespace_handler):
        """Register a namespace handler object.

        :param namespace_handler: An instance of a :class:`Namespace`
                                  subclass that handles all the event traffic
                                  for a namespace.
        """
        if not isinstance(namespace_handler,
                          base_namespace.BaseClientNamespace):
            raise ValueError('Not a namespace instance')
        if self.is_asyncio_based() != namespace_handler.is_asyncio_based():
            raise ValueError('Not a valid namespace class for this client')
        namespace_handler._set_client(self)
        self.namespace_handlers[namespace_handler.namespace] = \
            namespace_handler

    def get_sid(self, namespace=None):
        """Return the ``sid`` associated with a connection.

        :param namespace: The Socket.IO namespace. If this argument is omitted
                          the handler is associated with the default
                          namespace. Note that unlike previous versions, the
                          current version of the Socket.IO protocol uses
                          different ``sid`` values per namespace.

        This method returns the ``sid`` for the requested namespace as a
        string.
        """
        return self.namespaces.get(namespace or '/')

    def transport(self):
        """Return the name of the transport used by the client.

        The two possible values returned by this function are ``'polling'``
        and ``'websocket'``.
        """
        return self.eio.transport()

    def _get_event_handler(self, event, namespace, args):
        # return the appropriate application event handler
        #
        # Resolution priority:
        # - self.handlers[namespace][event]
        # - self.handlers[namespace]["*"]
        # - self.handlers["*"][event]
        # - self.handlers["*"]["*"]
        handler = None
        if namespace in self.handlers:
            if event in self.handlers[namespace]:
                handler = self.handlers[namespace][event]
            elif event not in self.reserved_events and \
                    '*' in self.handlers[namespace]:
                handler = self.handlers[namespace]['*']
                args = (event, *args)
        elif '*' in self.handlers:
            if event in self.handlers['*']:
                handler = self.handlers['*'][event]
                args = (namespace, *args)
            elif event not in self.reserved_events and \
                    '*' in self.handlers['*']:
                handler = self.handlers['*']['*']
                args = (event, namespace, *args)
        return handler, args

    def _get_namespace_handler(self, namespace, args):
        # Return the appropriate application event handler.
        #
        # Resolution priority:
        # - self.namespace_handlers[namespace]
        # - self.namespace_handlers["*"]
        handler = None
        if namespace in self.namespace_handlers:
            handler = self.namespace_handlers[namespace]
        elif '*' in self.namespace_handlers:
            handler = self.namespace_handlers['*']
            args = (namespace, *args)
        return handler, args

    def _generate_ack_id(self, namespace, callback):
        """Generate a unique identifier for an ACK packet."""
        namespace = namespace or '/'
        if namespace not in self.callbacks:
            self.callbacks[namespace] = {0: itertools.count(1)}
        id = next(self.callbacks[namespace][0])
        self.callbacks[namespace][id] = callback
        return id

    def _handle_eio_connect(self):  # pragma: no cover
        raise NotImplementedError()

    def _handle_eio_message(self, data):  # pragma: no cover
        raise NotImplementedError()

    def _handle_eio_disconnect(self, reason):  # pragma: no cover
        raise NotImplementedError()

    def _engineio_client_class(self):  # pragma: no cover
        raise NotImplementedError()
