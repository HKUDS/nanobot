import asyncio
from socketio import AsyncClient
from socketio.exceptions import SocketIOError, TimeoutError, DisconnectedError


class AsyncSimpleClient:
    """A Socket.IO client.

    This class implements a simple, yet fully compliant Socket.IO web client
    with support for websocket and long-polling transports.

    The positional and keyword arguments given in the constructor are passed
    to the underlying :func:`socketio.AsyncClient` object.
    """
    client_class = AsyncClient

    def __init__(self, *args, **kwargs):
        self.client_args = args
        self.client_kwargs = kwargs
        self.client = None
        self.namespace = '/'
        self.connected_event = asyncio.Event()
        self.connected = False
        self.input_event = asyncio.Event()
        self.input_buffer = []

    async def connect(self, url, headers={}, auth=None, transports=None,
                      namespace='/', socketio_path='socket.io',
                      wait_timeout=5):
        """Connect to a Socket.IO server.

        :param url: The URL of the Socket.IO server. It can include custom
                    query string parameters if required by the server. If a
                    function is provided, the client will invoke it to obtain
                    the URL each time a connection or reconnection is
                    attempted.
        :param headers: A dictionary with custom headers to send with the
                        connection request. If a function is provided, the
                        client will invoke it to obtain the headers dictionary
                        each time a connection or reconnection is attempted.
        :param auth: Authentication data passed to the server with the
                     connection request, normally a dictionary with one or
                     more string key/value pairs. If a function is provided,
                     the client will invoke it to obtain the authentication
                     data each time a connection or reconnection is attempted.
        :param transports: The list of allowed transports. Valid transports
                           are ``'polling'`` and ``'websocket'``. If not
                           given, the polling transport is connected first,
                           then an upgrade to websocket is attempted.
        :param namespace: The namespace to connect to as a string. If not
                          given, the default namespace ``/`` is used.
        :param socketio_path: The endpoint where the Socket.IO server is
                              installed. The default value is appropriate for
                              most cases.
        :param wait_timeout: How long the client should wait for the
                             connection. The default is 5 seconds.

        Note: this method is a coroutine.
        """
        if self.connected:
            raise RuntimeError('Already connected')
        self.namespace = namespace
        self.input_buffer = []
        self.input_event.clear()
        self.client = self.client_class(
            *self.client_args, **self.client_kwargs)

        @self.client.event(namespace=self.namespace)
        def connect():  # pragma: no cover
            self.connected = True
            self.connected_event.set()

        @self.client.event(namespace=self.namespace)
        def disconnect():  # pragma: no cover
            self.connected_event.clear()

        @self.client.event(namespace=self.namespace)
        def __disconnect_final():  # pragma: no cover
            self.connected = False
            self.connected_event.set()

        @self.client.on('*', namespace=self.namespace)
        def on_event(event, *args):  # pragma: no cover
            self.input_buffer.append([event, *args])
            self.input_event.set()

        await self.client.connect(
            url, headers=headers, auth=auth, transports=transports,
            namespaces=[namespace], socketio_path=socketio_path,
            wait_timeout=wait_timeout)

    @property
    def sid(self):
        """The session ID received from the server.

        The session ID is not guaranteed to remain constant throughout the life
        of the connection, as reconnections can cause it to change.
        """
        return self.client.get_sid(self.namespace) if self.client else None

    @property
    def transport(self):
        """The name of the transport currently in use.

        The transport is returned as a string and can be one of ``polling``
        and ``websocket``.
        """
        return self.client.transport() if self.client else ''

    async def emit(self, event, data=None):
        """Emit an event to the server.

        :param event: The event name. It can be any string. The event names
                      ``'connect'``, ``'message'`` and ``'disconnect'`` are
                      reserved and should not be used.
        :param data: The data to send to the server. Data can be of
                     type ``str``, ``bytes``, ``list`` or ``dict``. To send
                     multiple arguments, use a tuple where each element is of
                     one of the types indicated above.

        Note: this method is a coroutine.

        This method schedules the event to be sent out and returns, without
        actually waiting for its delivery. In cases where the client needs to
        ensure that the event was received, :func:`socketio.SimpleClient.call`
        should be used instead.
        """
        while True:
            await self.connected_event.wait()
            if not self.connected:
                raise DisconnectedError()
            try:
                return await self.client.emit(event, data,
                                              namespace=self.namespace)
            except SocketIOError:
                pass

    async def call(self, event, data=None, timeout=60):
        """Emit an event to the server and wait for a response.

        This method issues an emit and waits for the server to provide a
        response or acknowledgement. If the response does not arrive before the
        timeout, then a ``TimeoutError`` exception is raised.

        :param event: The event name. It can be any string. The event names
                      ``'connect'``, ``'message'`` and ``'disconnect'`` are
                      reserved and should not be used.
        :param data: The data to send to the server. Data can be of
                     type ``str``, ``bytes``, ``list`` or ``dict``. To send
                     multiple arguments, use a tuple where each element is of
                     one of the types indicated above.
        :param timeout: The waiting timeout. If the timeout is reached before
                        the server acknowledges the event, then a
                        ``TimeoutError`` exception is raised.

        Note: this method is a coroutine.
        """
        while True:
            await self.connected_event.wait()
            if not self.connected:
                raise DisconnectedError()
            try:
                return await self.client.call(event, data,
                                              namespace=self.namespace,
                                              timeout=timeout)
            except TimeoutError:
                raise
            except SocketIOError:
                pass

    async def receive(self, timeout=None):
        """Wait for an event from the server.

        :param timeout: The waiting timeout. If the timeout is reached before
                        the server acknowledges the event, then a
                        ``TimeoutError`` exception is raised.

        Note: this method is a coroutine.

        The return value is a list with the event name as the first element. If
        the server included arguments with the event, they are returned as
        additional list elements.
        """
        while not self.input_buffer:
            try:
                await asyncio.wait_for(self.connected_event.wait(),
                                       timeout=timeout)
            except asyncio.TimeoutError:  # pragma: no cover
                raise TimeoutError()
            if not self.connected:
                raise DisconnectedError()
            try:
                await asyncio.wait_for(self.input_event.wait(),
                                       timeout=timeout)
            except asyncio.TimeoutError:
                raise TimeoutError()
            self.input_event.clear()
        return self.input_buffer.pop(0)

    async def disconnect(self):
        """Disconnect from the server.

        Note: this method is a coroutine.
        """
        if self.connected:
            await self.client.disconnect()
            self.client = None
            self.connected = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
