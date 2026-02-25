import asyncio
import inspect
import logging
import random

import engineio

from . import base_client
from . import exceptions
from . import packet

default_logger = logging.getLogger('socketio.client')


class AsyncClient(base_client.BaseClient):
    """A Socket.IO client for asyncio.

    This class implements a fully compliant Socket.IO web client with support
    for websocket and long-polling transports.

    :param reconnection: ``True`` if the client should automatically attempt to
                         reconnect to the server after an interruption, or
                         ``False`` to not reconnect. The default is ``True``.
    :param reconnection_attempts: How many reconnection attempts to issue
                                  before giving up, or 0 for infinite attempts.
                                  The default is 0.
    :param reconnection_delay: How long to wait in seconds before the first
                               reconnection attempt. Each successive attempt
                               doubles this delay.
    :param reconnection_delay_max: The maximum delay between reconnection
                                   attempts.
    :param randomization_factor: Randomization amount for each delay between
                                 reconnection attempts. The default is 0.5,
                                 which means that each delay is randomly
                                 adjusted by +/- 50%.
    :param logger: To enable logging set to ``True`` or pass a logger object to
                   use. To disable logging set to ``False``. The default is
                   ``False``. Note that fatal errors are logged even when
                   ``logger`` is ``False``.
    :param json: An alternative JSON module to use for encoding and decoding
                 packets. Custom json modules must have ``dumps`` and ``loads``
                 functions that are compatible with the standard library
                 versions. This is a process-wide setting, all instantiated
                 servers and clients must use the same JSON module.
    :param handle_sigint: Set to ``True`` to automatically handle disconnection
                          when the process is interrupted, or to ``False`` to
                          leave interrupt handling to the calling application.
                          Interrupt handling can only be enabled when the
                          client instance is created in the main thread.

    The Engine.IO configuration supports the following settings:

    :param request_timeout: A timeout in seconds for requests. The default is
                            5 seconds.
    :param http_session: an initialized ``aiohttp.ClientSession`` object to be
                         used when sending requests to the server. Use it if
                         you need to add special client options such as proxy
                         servers, SSL certificates, custom CA bundle, etc.
    :param ssl_verify: ``True`` to verify SSL certificates, or ``False`` to
                       skip SSL certificate verification, allowing
                       connections to servers with self signed certificates.
                       The default is ``True``.
    :param websocket_extra_options: Dictionary containing additional keyword
                                    arguments passed to
                                    ``websocket.create_connection()``.
    :param engineio_logger: To enable Engine.IO logging set to ``True`` or pass
                            a logger object to use. To disable logging set to
                            ``False``. The default is ``False``. Note that
                            fatal errors are logged even when
                            ``engineio_logger`` is ``False``.
    """
    def is_asyncio_based(self):
        return True

    async def connect(self, url, headers={}, auth=None, transports=None,
                      namespaces=None, socketio_path='socket.io', wait=True,
                      wait_timeout=1, retry=False):
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
        :param namespaces: The namespaces to connect as a string or list of
                           strings. If not given, the namespaces that have
                           registered event handlers are connected.
        :param socketio_path: The endpoint where the Socket.IO server is
                              installed. The default value is appropriate for
                              most cases.
        :param wait: if set to ``True`` (the default) the call only returns
                     when all the namespaces are connected. If set to
                     ``False``, the call returns as soon as the Engine.IO
                     transport is connected, and the namespaces will connect
                     in the background.
        :param wait_timeout: How long the client should wait for the
                             connection. The default is 1 second. This
                             argument is only considered when ``wait`` is set
                             to ``True``.
        :param retry: Apply the reconnection logic if the initial connection
                      attempt fails. The default is ``False``.

        Note: this method is a coroutine.

        Example usage::

            sio = socketio.AsyncClient()
            await sio.connect('http://localhost:5000')
        """
        if self.connected:
            raise exceptions.ConnectionError('Already connected')

        self.connection_url = url
        self.connection_headers = headers
        self.connection_auth = auth
        self.connection_transports = transports
        self.connection_namespaces = namespaces
        self.socketio_path = socketio_path

        if namespaces is None:
            namespaces = list(set(self.handlers.keys()).union(
                set(self.namespace_handlers.keys())))
            if '*' in namespaces:
                namespaces.remove('*')
            if len(namespaces) == 0:
                namespaces = ['/']
        elif isinstance(namespaces, str):
            namespaces = [namespaces]
        self.connection_namespaces = namespaces
        self.namespaces = {}
        self.failed_namespaces = []
        if self._connect_event is None:
            self._connect_event = self.eio.create_event()
        else:
            self._connect_event.clear()
        real_url = await self._get_real_value(self.connection_url)
        real_headers = await self._get_real_value(self.connection_headers)
        try:
            await self.eio.connect(real_url, headers=real_headers,
                                   transports=transports,
                                   engineio_path=socketio_path)
        except engineio.exceptions.ConnectionError as exc:
            for n in self.connection_namespaces:
                await self._trigger_event(
                    'connect_error', n,
                    exc.args[1] if len(exc.args) > 1 else exc.args[0])
            if retry:  # pragma: no cover
                await self._handle_reconnect()
                if self.eio.state == 'connected':
                    return
            raise exceptions.ConnectionError(exc.args[0]) from exc

        if wait:
            try:
                while True:
                    await asyncio.wait_for(self._connect_event.wait(),
                                           wait_timeout)
                    self._connect_event.clear()
                    if len(self.namespaces) + len(self.failed_namespaces) == \
                            len(self.connection_namespaces):
                        break
            except asyncio.TimeoutError:
                pass
            if set(self.namespaces) != set(self.connection_namespaces):
                await self.disconnect()
                raise exceptions.ConnectionError(
                    'One or more namespaces failed to connect: '
                    + ', '.join(self.failed_namespaces))

        self.connected = True

    async def wait(self):
        """Wait until the connection with the server ends.

        Client applications can use this function to block the main thread
        during the life of the connection.

        Note: this method is a coroutine.
        """
        while True:
            await self.eio.wait()
            await self.sleep(1)  # give the reconnect task time to start up
            if not self._reconnect_task:
                if self.eio.state == 'connected':  # pragma: no cover
                    # connected while sleeping above
                    continue
                break
            await self._reconnect_task
            if self.eio.state != 'connected':
                break

    async def emit(self, event, data=None, namespace=None, callback=None):
        """Emit a custom event to the server.

        :param event: The event name. It can be any string. The event names
                      ``'connect'``, ``'message'`` and ``'disconnect'`` are
                      reserved and should not be used.
        :param data: The data to send to the server. Data can be of
                     type ``str``, ``bytes``, ``list`` or ``dict``. To send
                     multiple arguments, use a tuple where each element is of
                     one of the types indicated above.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the event is emitted to the
                          default namespace.
        :param callback: If given, this function will be called to acknowledge
                         the server has received the message. The arguments
                         that will be passed to the function are those provided
                         by the server.

        Note: this method is not designed to be used concurrently. If multiple
        tasks are emitting at the same time on the same client connection, then
        messages composed of multiple packets may end up being sent in an
        incorrect sequence. Use standard concurrency solutions (such as a Lock
        object) to prevent this situation.

        Note 2: this method is a coroutine.
        """
        namespace = namespace or '/'
        if namespace not in self.namespaces:
            raise exceptions.BadNamespaceError(
                namespace + ' is not a connected namespace.')
        self.logger.info('Emitting event "%s" [%s]', event, namespace)
        if callback is not None:
            id = self._generate_ack_id(namespace, callback)
        else:
            id = None
        # tuples are expanded to multiple arguments, everything else is sent
        # as a single argument
        if isinstance(data, tuple):
            data = list(data)
        elif data is not None:
            data = [data]
        else:
            data = []
        await self._send_packet(self.packet_class(
            packet.EVENT, namespace=namespace, data=[event] + data, id=id))

    async def send(self, data, namespace=None, callback=None):
        """Send a message to the server.

        This function emits an event with the name ``'message'``. Use
        :func:`emit` to issue custom event names.

        :param data: The data to send to the server. Data can be of
                     type ``str``, ``bytes``, ``list`` or ``dict``. To send
                     multiple arguments, use a tuple where each element is of
                     one of the types indicated above.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the event is emitted to the
                          default namespace.
        :param callback: If given, this function will be called to acknowledge
                         the server has received the message. The arguments
                         that will be passed to the function are those provided
                         by the server.

        Note: this method is a coroutine.
        """
        await self.emit('message', data=data, namespace=namespace,
                        callback=callback)

    async def call(self, event, data=None, namespace=None, timeout=60):
        """Emit a custom event to the server and wait for the response.

        This method issues an emit with a callback and waits for the callback
        to be invoked before returning. If the callback isn't invoked before
        the timeout, then a ``TimeoutError`` exception is raised. If the
        Socket.IO connection drops during the wait, this method still waits
        until the specified timeout.

        :param event: The event name. It can be any string. The event names
                      ``'connect'``, ``'message'`` and ``'disconnect'`` are
                      reserved and should not be used.
        :param data: The data to send to the server. Data can be of
                     type ``str``, ``bytes``, ``list`` or ``dict``. To send
                     multiple arguments, use a tuple where each element is of
                     one of the types indicated above.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the event is emitted to the
                          default namespace.
        :param timeout: The waiting timeout. If the timeout is reached before
                        the server acknowledges the event, then a
                        ``TimeoutError`` exception is raised.

        Note: this method is not designed to be used concurrently. If multiple
        tasks are emitting at the same time on the same client connection, then
        messages composed of multiple packets may end up being sent in an
        incorrect sequence. Use standard concurrency solutions (such as a Lock
        object) to prevent this situation.

        Note 2: this method is a coroutine.
        """
        callback_event = self.eio.create_event()
        callback_args = []

        def event_callback(*args):
            callback_args.append(args)
            callback_event.set()

        await self.emit(event, data=data, namespace=namespace,
                        callback=event_callback)
        try:
            await asyncio.wait_for(callback_event.wait(), timeout)
        except asyncio.TimeoutError:
            raise exceptions.TimeoutError() from None
        return callback_args[0] if len(callback_args[0]) > 1 \
            else callback_args[0][0] if len(callback_args[0]) == 1 \
            else None

    async def disconnect(self):
        """Disconnect from the server.

        Note: this method is a coroutine.
        """
        # here we just request the disconnection
        # later in _handle_eio_disconnect we invoke the disconnect handler
        for n in self.namespaces:
            await self._send_packet(self.packet_class(packet.DISCONNECT,
                                    namespace=n))
        await self.eio.disconnect()

    async def shutdown(self):
        """Stop the client.

        If the client is connected to a server, it is disconnected. If the
        client is attempting to reconnect to server, the reconnection attempts
        are stopped. If the client is not connected to a server and is not
        attempting to reconnect, then this function does nothing.
        """
        if self.connected:
            await self.disconnect()
        elif self._reconnect_task:  # pragma: no branch
            self._reconnect_abort.set()
            await self._reconnect_task

    def start_background_task(self, target, *args, **kwargs):
        """Start a background task using the appropriate async model.

        This is a utility function that applications can use to start a
        background task using the method that is compatible with the
        selected async mode.

        :param target: the target function to execute.
        :param args: arguments to pass to the function.
        :param kwargs: keyword arguments to pass to the function.

        The return value is a ``asyncio.Task`` object.
        """
        return self.eio.start_background_task(target, *args, **kwargs)

    async def sleep(self, seconds=0):
        """Sleep for the requested amount of time using the appropriate async
        model.

        This is a utility function that applications can use to put a task to
        sleep without having to worry about using the correct call for the
        selected async mode.

        Note: this method is a coroutine.
        """
        return await self.eio.sleep(seconds)

    async def _get_real_value(self, value):
        """Return the actual value, for parameters that can also be given as
        callables."""
        if not callable(value):
            return value
        if inspect.iscoroutinefunction(value):
            return await value()
        return value()

    async def _send_packet(self, pkt):
        """Send a Socket.IO packet to the server."""
        encoded_packet = pkt.encode()
        if isinstance(encoded_packet, list):
            for ep in encoded_packet:
                await self.eio.send(ep)
        else:
            await self.eio.send(encoded_packet)

    async def _handle_connect(self, namespace, data):
        namespace = namespace or '/'
        if namespace not in self.namespaces:
            self.logger.info(f'Namespace {namespace} is connected')
            self.namespaces[namespace] = (data or {}).get('sid', self.sid)
            await self._trigger_event('connect', namespace=namespace)
            self._connect_event.set()

    async def _handle_disconnect(self, namespace):
        if not self.connected:
            return
        namespace = namespace or '/'
        await self._trigger_event('disconnect', namespace,
                                  self.reason.SERVER_DISCONNECT)
        await self._trigger_event('__disconnect_final', namespace)
        if namespace in self.namespaces:
            del self.namespaces[namespace]
        if not self.namespaces:
            self.connected = False
            await self.eio.disconnect()

    async def _handle_event(self, namespace, id, data):
        namespace = namespace or '/'
        self.logger.info('Received event "%s" [%s]', data[0], namespace)
        r = await self._trigger_event(data[0], namespace, *data[1:])
        if id is not None:
            # send ACK packet with the response returned by the handler
            # tuples are expanded as multiple arguments
            if r is None:
                data = []
            elif isinstance(r, tuple):
                data = list(r)
            else:
                data = [r]
            await self._send_packet(self.packet_class(
                packet.ACK, namespace=namespace, id=id, data=data))

    async def _handle_ack(self, namespace, id, data):
        namespace = namespace or '/'
        self.logger.info('Received ack [%s]', namespace)
        callback = None
        try:
            callback = self.callbacks[namespace][id]
        except KeyError:
            # if we get an unknown callback we just ignore it
            self.logger.warning('Unknown callback received, ignoring.')
        else:
            del self.callbacks[namespace][id]
        if callback is not None:
            if inspect.iscoroutinefunction(callback):
                await callback(*data)
            else:
                callback(*data)

    async def _handle_error(self, namespace, data):
        namespace = namespace or '/'
        self.logger.info('Connection to namespace {} was rejected'.format(
            namespace))
        if data is None:
            data = tuple()
        elif not isinstance(data, (tuple, list)):
            data = (data,)
        await self._trigger_event('connect_error', namespace, *data)
        self.failed_namespaces.append(namespace)
        self._connect_event.set()
        if namespace in self.namespaces:
            del self.namespaces[namespace]
        if namespace == '/':
            self.namespaces = {}
            self.connected = False

    async def _trigger_event(self, event, namespace, *args):
        """Invoke an application event handler."""
        # first see if we have an explicit handler for the event
        handler, args = self._get_event_handler(event, namespace, args)
        if handler:
            if inspect.iscoroutinefunction(handler):
                try:
                    try:
                        ret = await handler(*args)
                    except TypeError:
                        # the legacy disconnect event does not take a reason
                        # argument
                        if event == 'disconnect':
                            ret = await handler(*args[:-1])
                        else:  # pragma: no cover
                            raise
                except asyncio.CancelledError:  # pragma: no cover
                    ret = None
            else:
                try:
                    ret = handler(*args)
                except TypeError:
                    # the legacy disconnect event does not take a reason
                    # argument
                    if event == 'disconnect':
                        ret = handler(*args[:-1])
                    else:  # pragma: no cover
                        raise
            return ret

        # or else, forward the event to a namespace handler if one exists
        handler, args = self._get_namespace_handler(namespace, args)
        if handler:
            return await handler.trigger_event(event, *args)

    async def _handle_reconnect(self):
        if self._reconnect_abort is None:  # pragma: no cover
            self._reconnect_abort = self.eio.create_event()
        self._reconnect_abort.clear()
        base_client.reconnecting_clients.append(self)
        attempt_count = 0
        current_delay = self.reconnection_delay
        while True:
            delay = current_delay
            current_delay *= 2
            if delay > self.reconnection_delay_max:
                delay = self.reconnection_delay_max
            delay += self.randomization_factor * (2 * random.random() - 1)
            self.logger.info(
                'Connection failed, new attempt in {:.02f} seconds'.format(
                    delay))
            abort = False
            try:
                await asyncio.wait_for(self._reconnect_abort.wait(), delay)
                abort = True
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:  # pragma: no cover
                abort = True
            if abort:
                self.logger.info('Reconnect task aborted')
                for n in self.connection_namespaces:
                    await self._trigger_event('__disconnect_final',
                                              namespace=n)
                break
            attempt_count += 1
            try:
                await self.connect(self.connection_url,
                                   headers=self.connection_headers,
                                   auth=self.connection_auth,
                                   transports=self.connection_transports,
                                   namespaces=self.connection_namespaces,
                                   socketio_path=self.socketio_path,
                                   retry=False)
            except (exceptions.ConnectionError, ValueError):
                pass
            else:
                self.logger.info('Reconnection successful')
                self._reconnect_task = None
                break
            if self.reconnection_attempts and \
                    attempt_count >= self.reconnection_attempts:
                self.logger.info(
                    'Maximum reconnection attempts reached, giving up')
                for n in self.connection_namespaces:
                    await self._trigger_event('__disconnect_final',
                                              namespace=n)
                break
        base_client.reconnecting_clients.remove(self)

    async def _handle_eio_connect(self):
        """Handle the Engine.IO connection event."""
        self.logger.info('Engine.IO connection established')
        self.sid = self.eio.sid
        real_auth = await self._get_real_value(self.connection_auth) or {}
        for n in self.connection_namespaces:
            await self._send_packet(self.packet_class(
                packet.CONNECT, data=real_auth, namespace=n))

    async def _handle_eio_message(self, data):
        """Dispatch Engine.IO messages."""
        if self._binary_packet:
            pkt = self._binary_packet
            if pkt.add_attachment(data):
                self._binary_packet = None
                if pkt.packet_type == packet.BINARY_EVENT:
                    await self._handle_event(pkt.namespace, pkt.id, pkt.data)
                else:
                    await self._handle_ack(pkt.namespace, pkt.id, pkt.data)
        else:
            pkt = self.packet_class(encoded_packet=data)
            if pkt.packet_type == packet.CONNECT:
                await self._handle_connect(pkt.namespace, pkt.data)
            elif pkt.packet_type == packet.DISCONNECT:
                await self._handle_disconnect(pkt.namespace)
            elif pkt.packet_type == packet.EVENT:
                await self._handle_event(pkt.namespace, pkt.id, pkt.data)
            elif pkt.packet_type == packet.ACK:
                await self._handle_ack(pkt.namespace, pkt.id, pkt.data)
            elif pkt.packet_type == packet.BINARY_EVENT or \
                    pkt.packet_type == packet.BINARY_ACK:
                self._binary_packet = pkt
            elif pkt.packet_type == packet.CONNECT_ERROR:
                await self._handle_error(pkt.namespace, pkt.data)
            else:
                raise ValueError('Unknown packet type.')

    async def _handle_eio_disconnect(self, reason):
        """Handle the Engine.IO disconnection event."""
        self.logger.info('Engine.IO connection dropped')
        will_reconnect = self.reconnection and self.eio.state == 'connected'
        if self.connected:
            for n in self.namespaces:
                await self._trigger_event('disconnect', n, reason)
                if not will_reconnect:
                    await self._trigger_event('__disconnect_final', n)
            self.namespaces = {}
            self.connected = False
        self.callbacks = {}
        self._binary_packet = None
        self.sid = None
        if will_reconnect and not self._reconnect_task:
            self._reconnect_task = self.start_background_task(
                self._handle_reconnect)

    def _engineio_client_class(self):
        return engineio.AsyncClient
