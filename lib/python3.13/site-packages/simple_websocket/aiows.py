import asyncio
import ssl
from time import time
from urllib.parse import urlsplit

from wsproto import ConnectionType, WSConnection
from wsproto.events import (
    AcceptConnection,
    RejectConnection,
    CloseConnection,
    Message,
    Request,
    Ping,
    Pong,
    TextMessage,
    BytesMessage,
)
from wsproto.extensions import PerMessageDeflate
from wsproto.frame_protocol import CloseReason
from wsproto.utilities import LocalProtocolError
from .errors import ConnectionError, ConnectionClosed


class AioBase:
    def __init__(self, connection_type=None, receive_bytes=4096,
                 ping_interval=None, max_message_size=None):
        #: The name of the subprotocol chosen for the WebSocket connection.
        self.subprotocol = None

        self.connection_type = connection_type
        self.receive_bytes = receive_bytes
        self.ping_interval = ping_interval
        self.max_message_size = max_message_size
        self.pong_received = True
        self.input_buffer = []
        self.incoming_message = None
        self.incoming_message_len = 0
        self.connected = False
        self.is_server = (connection_type == ConnectionType.SERVER)
        self.close_reason = CloseReason.NO_STATUS_RCVD
        self.close_message = None

        self.rsock = None
        self.wsock = None
        self.event = asyncio.Event()
        self.ws = None
        self.task = None

    async def connect(self):
        self.ws = WSConnection(self.connection_type)
        await self.handshake()

        if not self.connected:  # pragma: no cover
            raise ConnectionError()
        self.task = asyncio.create_task(self._task())

    async def handshake(self):  # pragma: no cover
        # to be implemented by subclasses
        pass

    async def send(self, data):
        """Send data over the WebSocket connection.

        :param data: The data to send. If ``data`` is of type ``bytes``, then
                     a binary message is sent. Else, the message is sent in
                     text format.
        """
        if not self.connected:
            raise ConnectionClosed(self.close_reason, self.close_message)
        if isinstance(data, bytes):
            out_data = self.ws.send(Message(data=data))
        else:
            out_data = self.ws.send(TextMessage(data=str(data)))
        self.wsock.write(out_data)

    async def receive(self, timeout=None):
        """Receive data over the WebSocket connection.

        :param timeout: Amount of time to wait for the data, in seconds. Set
                        to ``None`` (the default) to wait indefinitely. Set
                        to 0 to read without blocking.

        The data received is returned, as ``bytes`` or ``str``, depending on
        the type of the incoming message.
        """
        while self.connected and not self.input_buffer:
            try:
                await asyncio.wait_for(self.event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return None
            self.event.clear()  # pragma: no cover
        try:
            return self.input_buffer.pop(0)
        except IndexError:
            pass
        if not self.connected:  # pragma: no cover
            raise ConnectionClosed(self.close_reason, self.close_message)

    async def close(self, reason=None, message=None):
        """Close the WebSocket connection.

        :param reason: A numeric status code indicating the reason of the
                       closure, as defined by the WebSocket specification. The
                       default is 1000 (normal closure).
        :param message: A text message to be sent to the other side.
        """
        if not self.connected:
            raise ConnectionClosed(self.close_reason, self.close_message)
        out_data = self.ws.send(CloseConnection(
            reason or CloseReason.NORMAL_CLOSURE, message))
        try:
            self.wsock.write(out_data)
        except BrokenPipeError:  # pragma: no cover
            pass
        self.connected = False

    def choose_subprotocol(self, request):  # pragma: no cover
        # The method should return the subprotocol to use, or ``None`` if no
        # subprotocol is chosen. Can be overridden by subclasses that implement
        # the server-side of the WebSocket protocol.
        return None

    async def _task(self):
        next_ping = None
        if self.ping_interval:
            next_ping = time() + self.ping_interval

        while self.connected:
            try:
                in_data = b''
                if next_ping:
                    now = time()
                    timed_out = True
                    if next_ping > now:
                        timed_out = False
                        try:
                            in_data = await asyncio.wait_for(
                                self.rsock.read(self.receive_bytes),
                                timeout=next_ping - now)
                        except asyncio.TimeoutError:
                            timed_out = True
                    if timed_out:
                        # we reached the timeout, we have to send a ping
                        if not self.pong_received:
                            await self.close(
                                reason=CloseReason.POLICY_VIOLATION,
                                message='Ping/Pong timeout')
                            break
                        self.pong_received = False
                        self.wsock.write(self.ws.send(Ping()))
                        next_ping = max(now, next_ping) + self.ping_interval
                        continue
                else:
                    in_data = await self.rsock.read(self.receive_bytes)
                if len(in_data) == 0:
                    raise OSError()
            except (OSError, ConnectionResetError):  # pragma: no cover
                self.connected = False
                self.event.set()
                break

            self.ws.receive_data(in_data)
            self.connected = await self._handle_events()
        self.wsock.close()

    async def _handle_events(self):
        keep_going = True
        out_data = b''
        for event in self.ws.events():
            try:
                if isinstance(event, Request):
                    self.subprotocol = self.choose_subprotocol(event)
                    out_data += self.ws.send(AcceptConnection(
                        subprotocol=self.subprotocol,
                        extensions=[PerMessageDeflate()]))
                elif isinstance(event, CloseConnection):
                    if self.is_server:
                        out_data += self.ws.send(event.response())
                    self.close_reason = event.code
                    self.close_message = event.reason
                    self.connected = False
                    self.event.set()
                    keep_going = False
                elif isinstance(event, Ping):
                    out_data += self.ws.send(event.response())
                elif isinstance(event, Pong):
                    self.pong_received = True
                elif isinstance(event, (TextMessage, BytesMessage)):
                    self.incoming_message_len += len(event.data)
                    if self.max_message_size and \
                            self.incoming_message_len > self.max_message_size:
                        out_data += self.ws.send(CloseConnection(
                            CloseReason.MESSAGE_TOO_BIG, 'Message is too big'))
                        self.event.set()
                        keep_going = False
                        break
                    if self.incoming_message is None:
                        # store message as is first
                        # if it is the first of a group, the message will be
                        # converted to bytearray on arrival of the second
                        # part, since bytearrays are mutable and can be
                        # concatenated more efficiently
                        self.incoming_message = event.data
                    elif isinstance(event, TextMessage):
                        if not isinstance(self.incoming_message, bytearray):
                            # convert to bytearray and append
                            self.incoming_message = bytearray(
                                (self.incoming_message + event.data).encode())
                        else:
                            # append to bytearray
                            self.incoming_message += event.data.encode()
                    else:
                        if not isinstance(self.incoming_message, bytearray):
                            # convert to mutable bytearray and append
                            self.incoming_message = bytearray(
                                self.incoming_message + event.data)
                        else:
                            # append to bytearray
                            self.incoming_message += event.data
                    if not event.message_finished:
                        continue
                    if isinstance(self.incoming_message, (str, bytes)):
                        # single part message
                        self.input_buffer.append(self.incoming_message)
                    elif isinstance(event, TextMessage):
                        # convert multi-part message back to text
                        self.input_buffer.append(
                            self.incoming_message.decode())
                    else:
                        # convert multi-part message back to bytes
                        self.input_buffer.append(bytes(self.incoming_message))
                    self.incoming_message = None
                    self.incoming_message_len = 0
                    self.event.set()
                else:  # pragma: no cover
                    pass
            except LocalProtocolError:  # pragma: no cover
                out_data = b''
                self.event.set()
                keep_going = False
        if out_data:
            self.wsock.write(out_data)
        return keep_going


class AioServer(AioBase):
    """This class implements a WebSocket server.

    Instead of creating an instance of this class directly, use the
    ``accept()`` class method to create individual instances of the server,
    each bound to a client request.
    """
    def __init__(self, request, subprotocols=None, receive_bytes=4096,
                 ping_interval=None, max_message_size=None):
        super().__init__(connection_type=ConnectionType.SERVER,
                         receive_bytes=receive_bytes,
                         ping_interval=ping_interval,
                         max_message_size=max_message_size)
        self.request = request
        self.headers = {}
        self.subprotocols = subprotocols or []
        if isinstance(self.subprotocols, str):
            self.subprotocols = [self.subprotocols]
        self.mode = 'unknown'

    @classmethod
    async def accept(cls, aiohttp=None, asgi=None, sock=None, headers=None,
                     subprotocols=None, receive_bytes=4096, ping_interval=None,
                     max_message_size=None):
        """Accept a WebSocket connection from a client.

        :param aiohttp: The request object from aiohttp. If this argument is
                        provided, ``asgi``, ``sock`` and ``headers`` must not
                        be set.
        :param asgi: A (scope, receive, send) tuple from an ASGI request. If
                     this argument is provided, ``aiohttp``, ``sock`` and
                     ``headers`` must not be set.
        :param sock: A connected socket to use. If this argument is provided,
                     ``aiohttp`` and ``asgi`` must not be set. The ``headers``
                     argument must be set with the incoming request headers.
        :param headers: A dictionary with the incoming request headers, when
                        ``sock`` is used.
        :param subprotocols: A list of supported subprotocols, or ``None`` (the
                             default) to disable subprotocol negotiation.
        :param receive_bytes: The size of the receive buffer, in bytes. The
                              default is 4096.
        :param ping_interval: Send ping packets to clients at the requested
                              interval in seconds. Set to ``None`` (the
                              default) to disable ping/pong logic. Enable to
                              prevent disconnections when the line is idle for
                              a certain amount of time, or to detect
                              unresponsive clients and disconnect them. A
                              recommended interval is 25 seconds.
        :param max_message_size: The maximum size allowed for a message, in
                                 bytes, or ``None`` for no limit. The default
                                 is ``None``.
        """
        if aiohttp and (asgi or sock):
            raise ValueError('aiohttp argument cannot be used with asgi or '
                             'sock')
        if asgi and (aiohttp or sock):
            raise ValueError('asgi argument cannot be used with aiohttp or '
                             'sock')
        if asgi:  # pragma: no cover
            from .asgi import WebSocketASGI
            return await WebSocketASGI.accept(asgi[0], asgi[1], asgi[2],
                                              subprotocols=subprotocols)

        ws = cls({'aiohttp': aiohttp, 'sock': sock, 'headers': headers},
                 subprotocols=subprotocols, receive_bytes=receive_bytes,
                 ping_interval=ping_interval,
                 max_message_size=max_message_size)
        await ws._accept()
        return ws

    async def _accept(self):
        if self.request['sock']:  # pragma: no cover
            # custom integration, request is a tuple with (socket, headers)
            sock = self.request['sock']
            self.headers = self.request['headers']
            self.mode = 'custom'
        elif self.request['aiohttp']:
            # default implementation, request is an aiohttp request object
            sock = self.request['aiohttp'].transport.get_extra_info(
                'socket').dup()
            self.headers = self.request['aiohttp'].headers
            self.mode = 'aiohttp'
        else:  # pragma: no cover
            raise ValueError('Invalid request')
        self.rsock, self.wsock = await asyncio.open_connection(sock=sock)
        await super().connect()

    async def handshake(self):
        in_data = b'GET / HTTP/1.1\r\n'
        for header, value in self.headers.items():
            in_data += f'{header}: {value}\r\n'.encode()
        in_data += b'\r\n'
        self.ws.receive_data(in_data)
        self.connected = await self._handle_events()

    def choose_subprotocol(self, request):
        """Choose a subprotocol to use for the WebSocket connection.

        The default implementation selects the first protocol requested by the
        client that is accepted by the server. Subclasses can override this
        method to implement a different subprotocol negotiation algorithm.

        :param request: A ``Request`` object.

        The method should return the subprotocol to use, or ``None`` if no
        subprotocol is chosen.
        """
        for subprotocol in request.subprotocols:
            if subprotocol in self.subprotocols:
                return subprotocol
        return None


class AioClient(AioBase):
    """This class implements a WebSocket client.

    Instead of creating an instance of this class directly, use the
    ``connect()`` class method to create an instance that is connected to a
    server.
    """
    def __init__(self, url, subprotocols=None, headers=None,
                 receive_bytes=4096, ping_interval=None, max_message_size=None,
                 ssl_context=None):
        super().__init__(connection_type=ConnectionType.CLIENT,
                         receive_bytes=receive_bytes,
                         ping_interval=ping_interval,
                         max_message_size=max_message_size)
        self.url = url
        self.ssl_context = ssl_context
        parsed_url = urlsplit(url)
        self.is_secure = parsed_url.scheme in ['https', 'wss']
        self.host = parsed_url.hostname
        self.port = parsed_url.port or (443 if self.is_secure else 80)
        self.path = parsed_url.path
        if parsed_url.query:
            self.path += '?' + parsed_url.query
        self.subprotocols = subprotocols or []
        if isinstance(self.subprotocols, str):
            self.subprotocols = [self.subprotocols]

        self.extra_headeers = []
        if isinstance(headers, dict):
            for key, value in headers.items():
                self.extra_headeers.append((key, value))
        elif isinstance(headers, list):
            self.extra_headeers = headers

    @classmethod
    async def connect(cls, url, subprotocols=None, headers=None,
                      receive_bytes=4096, ping_interval=None,
                      max_message_size=None, ssl_context=None,
                      thread_class=None, event_class=None):
        """Returns a WebSocket client connection.

        :param url: The connection URL. Both ``ws://`` and ``wss://`` URLs are
                    accepted.
        :param subprotocols: The name of the subprotocol to use, or a list of
                             subprotocol names in order of preference. Set to
                             ``None`` (the default) to not use a subprotocol.
        :param headers: A dictionary or list of tuples with additional HTTP
                        headers to send with the connection request. Note that
                        custom headers are not supported by the WebSocket
                        protocol, so the use of this parameter is not
                        recommended.
        :param receive_bytes: The size of the receive buffer, in bytes. The
                              default is 4096.
        :param ping_interval: Send ping packets to the server at the requested
                              interval in seconds. Set to ``None`` (the
                              default) to disable ping/pong logic. Enable to
                              prevent disconnections when the line is idle for
                              a certain amount of time, or to detect an
                              unresponsive server and disconnect. A recommended
                              interval is 25 seconds. In general it is
                              preferred to enable ping/pong on the server, and
                              let the client respond with pong (which it does
                              regardless of this setting).
        :param max_message_size: The maximum size allowed for a message, in
                                 bytes, or ``None`` for no limit. The default
                                 is ``None``.
        :param ssl_context: An ``SSLContext`` instance, if a default SSL
                            context isn't sufficient.
        """
        ws = cls(url, subprotocols=subprotocols, headers=headers,
                 receive_bytes=receive_bytes, ping_interval=ping_interval,
                 max_message_size=max_message_size, ssl_context=ssl_context)
        await ws._connect()
        return ws

    async def _connect(self):
        if self.is_secure:  # pragma: no cover
            if self.ssl_context is None:
                self.ssl_context = ssl.create_default_context(
                    purpose=ssl.Purpose.SERVER_AUTH)
        self.rsock, self.wsock = await asyncio.open_connection(
            self.host, self.port, ssl=self.ssl_context)
        await super().connect()

    async def handshake(self):
        out_data = self.ws.send(Request(host=self.host, target=self.path,
                                        subprotocols=self.subprotocols,
                                        extra_headers=self.extra_headeers))
        self.wsock.write(out_data)

        while True:
            in_data = await self.rsock.read(self.receive_bytes)
            self.ws.receive_data(in_data)
            try:
                event = next(self.ws.events())
            except StopIteration:  # pragma: no cover
                pass
            else:  # pragma: no cover
                break
        if isinstance(event, RejectConnection):  # pragma: no cover
            raise ConnectionError(event.status_code)
        elif not isinstance(event, AcceptConnection):  # pragma: no cover
            raise ConnectionError(400)
        self.subprotocol = event.subprotocol
        self.connected = True

    async def close(self, reason=None, message=None):
        await super().close(reason=reason, message=message)
        self.wsock.close()
