import logging

import engineio

from . import base_server
from . import exceptions
from . import packet

default_logger = logging.getLogger('socketio.server')


class Server(base_server.BaseServer):
    """A Socket.IO server.

    This class implements a fully compliant Socket.IO web server with support
    for websocket and long-polling transports.

    :param client_manager: The client manager instance that will manage the
                           client list. When this is omitted, the client list
                           is stored in an in-memory structure, so the use of
                           multiple connected servers is not possible.
    :param logger: To enable logging set to ``True`` or pass a logger object to
                   use. To disable logging set to ``False``. The default is
                   ``False``. Note that fatal errors are logged even when
                   ``logger`` is ``False``.
    :param serializer: The serialization method to use when transmitting
                       packets. Valid values are ``'default'``, ``'pickle'``,
                       ``'msgpack'`` and ``'cbor'``. Alternatively, a subclass
                       of the :class:`Packet` class with custom implementations
                       of the ``encode()`` and ``decode()`` methods can be
                       provided. Client and server must use compatible
                       serializers.
    :param json: An alternative JSON module to use for encoding and decoding
                 packets. Custom json modules must have ``dumps`` and ``loads``
                 functions that are compatible with the standard library
                 versions. This is a process-wide setting, all instantiated
                 servers and clients must use the same JSON module.
    :param async_handlers: If set to ``True``, event handlers for a client are
                           executed in separate threads. To run handlers for a
                           client synchronously, set to ``False``. The default
                           is ``True``.
    :param always_connect: When set to ``False``, new connections are
                           provisory until the connect handler returns
                           something other than ``False``, at which point they
                           are accepted. When set to ``True``, connections are
                           immediately accepted, and then if the connect
                           handler returns ``False`` a disconnect is issued.
                           Set to ``True`` if you need to emit events from the
                           connect handler and your client is confused when it
                           receives events before the connection acceptance.
                           In any other case use the default of ``False``.
    :param namespaces: a list of namespaces that are accepted, in addition to
                       any namespaces for which handlers have been defined. The
                       default is `['/']`, which always accepts connections to
                       the default namespace. Set to `'*'` to accept all
                       namespaces.
    :param kwargs: Connection parameters for the underlying Engine.IO server.

    The Engine.IO configuration supports the following settings:

    :param async_mode: The asynchronous model to use. See the Deployment
                       section in the documentation for a description of the
                       available options. Valid async modes are
                       ``'threading'``, ``'eventlet'``, ``'gevent'`` and
                       ``'gevent_uwsgi'``. If this argument is not given,
                       ``'eventlet'`` is tried first, then ``'gevent_uwsgi'``,
                       then ``'gevent'``, and finally ``'threading'``.
                       The first async mode that has all its dependencies
                       installed is then one that is chosen.
    :param ping_interval: The interval in seconds at which the server pings
                          the client. The default is 25 seconds. For advanced
                          control, a two element tuple can be given, where
                          the first number is the ping interval and the second
                          is a grace period added by the server.
    :param ping_timeout: The time in seconds that the client waits for the
                         server to respond before disconnecting. The default
                         is 20 seconds.
    :param max_http_buffer_size: The maximum size that is accepted for incoming
                                 messages.  The default is 1,000,000 bytes. In
                                 spite of its name, the value set in this
                                 argument is enforced for HTTP long-polling and
                                 WebSocket connections.
    :param allow_upgrades: Whether to allow transport upgrades or not. The
                           default is ``True``.
    :param http_compression: Whether to compress packages when using the
                             polling transport. The default is ``True``.
    :param compression_threshold: Only compress messages when their byte size
                                  is greater than this value. The default is
                                  1024 bytes.
    :param cookie: If set to a string, it is the name of the HTTP cookie the
                   server sends back to the client containing the client
                   session id. If set to a dictionary, the ``'name'`` key
                   contains the cookie name and other keys define cookie
                   attributes, where the value of each attribute can be a
                   string, a callable with no arguments, or a boolean. If set
                   to ``None`` (the default), a cookie is not sent to the
                   client.
    :param cors_allowed_origins: Origin or list of origins that are allowed to
                                 connect to this server. Only the same origin
                                 is allowed by default. Set this argument to
                                 ``'*'`` to allow all origins, or to ``[]`` to
                                 disable CORS handling.
    :param cors_credentials: Whether credentials (cookies, authentication) are
                             allowed in requests to this server. The default is
                             ``True``.
    :param monitor_clients: If set to ``True``, a background task will ensure
                            inactive clients are closed. Set to ``False`` to
                            disable the monitoring task (not recommended). The
                            default is ``True``.
    :param transports: The list of allowed transports. Valid transports
                       are ``'polling'`` and ``'websocket'``. Defaults to
                       ``['polling', 'websocket']``.
    :param engineio_logger: To enable Engine.IO logging set to ``True`` or pass
                            a logger object to use. To disable logging set to
                            ``False``. The default is ``False``. Note that
                            fatal errors are logged even when
                            ``engineio_logger`` is ``False``.
    """
    def emit(self, event, data=None, to=None, room=None, skip_sid=None,
             namespace=None, callback=None, ignore_queue=False):
        """Emit a custom event to one or more connected clients.

        :param event: The event name. It can be any string. The event names
                      ``'connect'``, ``'message'`` and ``'disconnect'`` are
                      reserved and should not be used.
        :param data: The data to send to the client or clients. Data can be of
                     type ``str``, ``bytes``, ``list`` or ``dict``. To send
                     multiple arguments, use a tuple where each element is of
                     one of the types indicated above.
        :param to: The recipient of the message. This can be set to the
                   session ID of a client to address only that client, to any
                   custom room created by the application to address all
                   the clients in that room, or to a list of custom room
                   names. If this argument is omitted the event is broadcasted
                   to all connected clients.
        :param room: Alias for the ``to`` parameter.
        :param skip_sid: The session ID of a client to skip when broadcasting
                         to a room or to all clients. This can be used to
                         prevent a message from being sent to the sender. To
                         skip multiple sids, pass a list.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the event is emitted to the
                          default namespace.
        :param callback: If given, this function will be called to acknowledge
                         the client has received the message. The arguments
                         that will be passed to the function are those provided
                         by the client. Callback functions can only be used
                         when addressing an individual client.
        :param ignore_queue: Only used when a message queue is configured. If
                             set to ``True``, the event is emitted to the
                             clients directly, without going through the queue.
                             This is more efficient, but only works when a
                             single server process is used. It is recommended
                             to always leave this parameter with its default
                             value of ``False``.

        Note: this method is not thread safe. If multiple threads are emitting
        at the same time to the same client, then messages composed of
        multiple packets may end up being sent in an incorrect sequence. Use
        standard concurrency solutions (such as a Lock object) to prevent this
        situation.
        """
        namespace = namespace or '/'
        room = to or room
        self.logger.info('emitting event "%s" to %s [%s]', event,
                         room or 'all', namespace)
        self.manager.emit(event, data, namespace, room=room,
                          skip_sid=skip_sid, callback=callback,
                          ignore_queue=ignore_queue)

    def send(self, data, to=None, room=None, skip_sid=None, namespace=None,
             callback=None, ignore_queue=False):
        """Send a message to one or more connected clients.

        This function emits an event with the name ``'message'``. Use
        :func:`emit` to issue custom event names.

        :param data: The data to send to the client or clients. Data can be of
                     type ``str``, ``bytes``, ``list`` or ``dict``. To send
                     multiple arguments, use a tuple where each element is of
                     one of the types indicated above.
        :param to: The recipient of the message. This can be set to the
                   session ID of a client to address only that client, to any
                   any custom room created by the application to address all
                   the clients in that room, or to a list of custom room
                   names. If this argument is omitted the event is broadcasted
                   to all connected clients.
        :param room: Alias for the ``to`` parameter.
        :param skip_sid: The session ID of a client to skip when broadcasting
                         to a room or to all clients. This can be used to
                         prevent a message from being sent to the sender. To
                         skip multiple sids, pass a list.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the event is emitted to the
                          default namespace.
        :param callback: If given, this function will be called to acknowledge
                         the client has received the message. The arguments
                         that will be passed to the function are those provided
                         by the client. Callback functions can only be used
                         when addressing an individual client.
        :param ignore_queue: Only used when a message queue is configured. If
                             set to ``True``, the event is emitted to the
                             clients directly, without going through the queue.
                             This is more efficient, but only works when a
                             single server process is used. It is recommended
                             to always leave this parameter with its default
                             value of ``False``.
        """
        self.emit('message', data=data, to=to, room=room, skip_sid=skip_sid,
                  namespace=namespace, callback=callback,
                  ignore_queue=ignore_queue)

    def call(self, event, data=None, to=None, sid=None, namespace=None,
             timeout=60, ignore_queue=False):
        """Emit a custom event to a client and wait for the response.

        This method issues an emit with a callback and waits for the callback
        to be invoked before returning. If the callback isn't invoked before
        the timeout, then a ``TimeoutError`` exception is raised. If the
        Socket.IO connection drops during the wait, this method still waits
        until the specified timeout.

        :param event: The event name. It can be any string. The event names
                      ``'connect'``, ``'message'`` and ``'disconnect'`` are
                      reserved and should not be used.
        :param data: The data to send to the client or clients. Data can be of
                     type ``str``, ``bytes``, ``list`` or ``dict``. To send
                     multiple arguments, use a tuple where each element is of
                     one of the types indicated above.
        :param to: The session ID of the recipient client.
        :param sid: Alias for the ``to`` parameter.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the event is emitted to the
                          default namespace.
        :param timeout: The waiting timeout. If the timeout is reached before
                        the client acknowledges the event, then a
                        ``TimeoutError`` exception is raised.
        :param ignore_queue: Only used when a message queue is configured. If
                             set to ``True``, the event is emitted to the
                             client directly, without going through the queue.
                             This is more efficient, but only works when a
                             single server process is used. It is recommended
                             to always leave this parameter with its default
                             value of ``False``.

        Note: this method is not thread safe. If multiple threads are emitting
        at the same time to the same client, then messages composed of
        multiple packets may end up being sent in an incorrect sequence. Use
        standard concurrency solutions (such as a Lock object) to prevent this
        situation.
        """
        if to is None and sid is None:
            raise ValueError('Cannot use call() to broadcast.')
        if not self.async_handlers:
            raise RuntimeError(
                'Cannot use call() when async_handlers is False.')
        callback_event = self.eio.create_event()
        callback_args = []

        def event_callback(*args):
            callback_args.append(args)
            callback_event.set()

        self.emit(event, data=data, room=to or sid, namespace=namespace,
                  callback=event_callback, ignore_queue=ignore_queue)
        if not callback_event.wait(timeout=timeout):
            raise exceptions.TimeoutError()
        return callback_args[0] if len(callback_args[0]) > 1 \
            else callback_args[0][0] if len(callback_args[0]) == 1 \
            else None

    def enter_room(self, sid, room, namespace=None):
        """Enter a room.

        This function adds the client to a room. The :func:`emit` and
        :func:`send` functions can optionally broadcast events to all the
        clients in a room.

        :param sid: Session ID of the client.
        :param room: Room name. If the room does not exist it is created.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the default namespace is used.
        """
        namespace = namespace or '/'
        self.logger.info('%s is entering room %s [%s]', sid, room, namespace)
        self.manager.enter_room(sid, namespace, room)

    def leave_room(self, sid, room, namespace=None):
        """Leave a room.

        This function removes the client from a room.

        :param sid: Session ID of the client.
        :param room: Room name.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the default namespace is used.
        """
        namespace = namespace or '/'
        self.logger.info('%s is leaving room %s [%s]', sid, room, namespace)
        self.manager.leave_room(sid, namespace, room)

    def close_room(self, room, namespace=None):
        """Close a room.

        This function removes all the clients from the given room.

        :param room: Room name.
        :param namespace: The Socket.IO namespace for the event. If this
                          argument is omitted the default namespace is used.
        """
        namespace = namespace or '/'
        self.logger.info('room %s is closing [%s]', room, namespace)
        self.manager.close_room(room, namespace)

    def get_session(self, sid, namespace=None):
        """Return the user session for a client.

        :param sid: The session id of the client.
        :param namespace: The Socket.IO namespace. If this argument is omitted
                          the default namespace is used.

        The return value is a dictionary. Modifications made to this
        dictionary are not guaranteed to be preserved unless
        ``save_session()`` is called, or when the ``session`` context manager
        is used.
        """
        namespace = namespace or '/'
        eio_sid = self.manager.eio_sid_from_sid(sid, namespace)
        eio_session = self.eio.get_session(eio_sid)
        return eio_session.setdefault(namespace, {})

    def save_session(self, sid, session, namespace=None):
        """Store the user session for a client.

        :param sid: The session id of the client.
        :param session: The session dictionary.
        :param namespace: The Socket.IO namespace. If this argument is omitted
                          the default namespace is used.
        """
        namespace = namespace or '/'
        eio_sid = self.manager.eio_sid_from_sid(sid, namespace)
        eio_session = self.eio.get_session(eio_sid)
        eio_session[namespace] = session

    def session(self, sid, namespace=None):
        """Return the user session for a client with context manager syntax.

        :param sid: The session id of the client.

        This is a context manager that returns the user session dictionary for
        the client. Any changes that are made to this dictionary inside the
        context manager block are saved back to the session. Example usage::

            @sio.on('connect')
            def on_connect(sid, environ):
                username = authenticate_user(environ)
                if not username:
                    return False
                with sio.session(sid) as session:
                    session['username'] = username

            @sio.on('message')
            def on_message(sid, msg):
                with sio.session(sid) as session:
                    print('received message from ', session['username'])
        """
        class _session_context_manager:
            def __init__(self, server, sid, namespace):
                self.server = server
                self.sid = sid
                self.namespace = namespace
                self.session = None

            def __enter__(self):
                self.session = self.server.get_session(sid,
                                                       namespace=namespace)
                return self.session

            def __exit__(self, *args):
                self.server.save_session(sid, self.session,
                                         namespace=namespace)

        return _session_context_manager(self, sid, namespace)

    def disconnect(self, sid, namespace=None, ignore_queue=False):
        """Disconnect a client.

        :param sid: Session ID of the client.
        :param namespace: The Socket.IO namespace to disconnect. If this
                          argument is omitted the default namespace is used.
        :param ignore_queue: Only used when a message queue is configured. If
                             set to ``True``, the disconnect is processed
                             locally, without broadcasting on the queue. It is
                             recommended to always leave this parameter with
                             its default value of ``False``.
        """
        namespace = namespace or '/'
        if ignore_queue:
            delete_it = self.manager.is_connected(sid, namespace)
        else:
            delete_it = self.manager.can_disconnect(sid, namespace)
        if delete_it:
            self.logger.info('Disconnecting %s [%s]', sid, namespace)
            eio_sid = self.manager.pre_disconnect(sid, namespace=namespace)
            self._send_packet(eio_sid, self.packet_class(
                packet.DISCONNECT, namespace=namespace))
            self._trigger_event('disconnect', namespace, sid,
                                self.reason.SERVER_DISCONNECT)
            self.manager.disconnect(sid, namespace=namespace,
                                    ignore_queue=True)

    def shutdown(self):
        """Stop Socket.IO background tasks.

        This method stops all background activity initiated by the Socket.IO
        server. It must be called before shutting down the web server.
        """
        self.logger.info('Socket.IO is shutting down')
        self.eio.shutdown()

    def handle_request(self, environ, start_response):
        """Handle an HTTP request from the client.

        This is the entry point of the Socket.IO application, using the same
        interface as a WSGI application. For the typical usage, this function
        is invoked by the :class:`Middleware` instance, but it can be invoked
        directly when the middleware is not used.

        :param environ: The WSGI environment.
        :param start_response: The WSGI ``start_response`` function.

        This function returns the HTTP response body to deliver to the client
        as a byte sequence.
        """
        return self.eio.handle_request(environ, start_response)

    def start_background_task(self, target, *args, **kwargs):
        """Start a background task using the appropriate async model.

        This is a utility function that applications can use to start a
        background task using the method that is compatible with the
        selected async mode.

        :param target: the target function to execute.
        :param args: arguments to pass to the function.
        :param kwargs: keyword arguments to pass to the function.

        This function returns an object that represents the background task,
        on which the ``join()`` methond can be invoked to wait for the task to
        complete.
        """
        return self.eio.start_background_task(target, *args, **kwargs)

    def sleep(self, seconds=0):
        """Sleep for the requested amount of time using the appropriate async
        model.

        This is a utility function that applications can use to put a task to
        sleep without having to worry about using the correct call for the
        selected async mode.
        """
        return self.eio.sleep(seconds)

    def instrument(self, auth=None, mode='development', read_only=False,
                   server_id=None, namespace='/admin',
                   server_stats_interval=2):
        """Instrument the Socket.IO server for monitoring with the `Socket.IO
        Admin UI <https://socket.io/docs/v4/admin-ui/>`_.

        :param auth: Authentication credentials for Admin UI access. Set to a
                     dictionary with the expected login (usually ``username``
                     and ``password``) or a list of dictionaries if more than
                     one set of credentials need to be available. For more
                     complex authentication methods, set to a callable that
                     receives the authentication dictionary as an argument and
                     returns ``True`` if the user is allowed or ``False``
                     otherwise. To disable authentication, set this argument to
                     ``False`` (not recommended, never do this on a production
                     server).
        :param mode: The reporting mode. The default is ``'development'``,
                     which is best used while debugging, as it may have a
                     significant performance effect. Set to ``'production'`` to
                     reduce the amount of information that is reported to the
                     admin UI.
        :param read_only: If set to ``True``, the admin interface will be
                          read-only, with no option to modify room assignments
                          or disconnect clients. The default is ``False``.
        :param server_id: The server name to use for this server. If this
                          argument is omitted, the server generates its own
                          name.
        :param namespace: The Socket.IO namespace to use for the admin
                          interface. The default is ``/admin``.
        :param server_stats_interval: The interval in seconds at which the
                                      server emits a summary of it stats to all
                                      connected admins.
        """
        from .admin import InstrumentedServer
        return InstrumentedServer(
            self, auth=auth, mode=mode, read_only=read_only,
            server_id=server_id, namespace=namespace,
            server_stats_interval=server_stats_interval)

    def _send_packet(self, eio_sid, pkt):
        """Send a Socket.IO packet to a client."""
        encoded_packet = pkt.encode()
        if isinstance(encoded_packet, list):
            for ep in encoded_packet:
                self.eio.send(eio_sid, ep)
        else:
            self.eio.send(eio_sid, encoded_packet)

    def _send_eio_packet(self, eio_sid, eio_pkt):
        """Send a raw Engine.IO packet to a client."""
        self.eio.send_packet(eio_sid, eio_pkt)

    def _handle_connect(self, eio_sid, namespace, data):
        """Handle a client connection request."""
        namespace = namespace or '/'
        sid = None
        if namespace in self.handlers or namespace in self.namespace_handlers \
                or self.namespaces == '*' or namespace in self.namespaces:
            sid = self.manager.connect(eio_sid, namespace)
        if sid is None:
            self._send_packet(eio_sid, self.packet_class(
                packet.CONNECT_ERROR, data='Unable to connect',
                namespace=namespace))
            return

        if self.always_connect:
            self._send_packet(eio_sid, self.packet_class(
                packet.CONNECT, {'sid': sid}, namespace=namespace))
        fail_reason = exceptions.ConnectionRefusedError().error_args
        try:
            if data:
                success = self._trigger_event(
                    'connect', namespace, sid, self.environ[eio_sid], data)
            else:
                try:
                    success = self._trigger_event(
                        'connect', namespace, sid, self.environ[eio_sid])
                except TypeError:
                    success = self._trigger_event(
                        'connect', namespace, sid, self.environ[eio_sid], None)
        except exceptions.ConnectionRefusedError as exc:
            fail_reason = exc.error_args
            success = False
        except ConnectionRefusedError:
            fail_reason = {"message": "Connection refused by server"}
            success = False

        if success is False:
            if self.always_connect:
                self.manager.pre_disconnect(sid, namespace)
                self._send_packet(eio_sid, self.packet_class(
                    packet.DISCONNECT, data=fail_reason, namespace=namespace))
            else:
                self._send_packet(eio_sid, self.packet_class(
                    packet.CONNECT_ERROR, data=fail_reason,
                    namespace=namespace))
            self.manager.disconnect(sid, namespace, ignore_queue=True)
        elif not self.always_connect:
            self._send_packet(eio_sid, self.packet_class(
                packet.CONNECT, {'sid': sid}, namespace=namespace))

    def _handle_disconnect(self, eio_sid, namespace, reason=None):
        """Handle a client disconnect."""
        namespace = namespace or '/'
        sid = self.manager.sid_from_eio_sid(eio_sid, namespace)
        if not self.manager.is_connected(sid, namespace):  # pragma: no cover
            return
        self.manager.pre_disconnect(sid, namespace=namespace)
        self._trigger_event('disconnect', namespace, sid,
                            reason or self.reason.CLIENT_DISCONNECT)
        self.manager.disconnect(sid, namespace, ignore_queue=True)

    def _handle_event(self, eio_sid, namespace, id, data):
        """Handle an incoming client event."""
        namespace = namespace or '/'
        sid = self.manager.sid_from_eio_sid(eio_sid, namespace)
        self.logger.info('received event "%s" from %s [%s]', data[0], sid,
                         namespace)
        if not self.manager.is_connected(sid, namespace):
            self.logger.warning('%s is not connected to namespace %s',
                                sid, namespace)
            return
        if self.async_handlers:
            self.start_background_task(self._handle_event_internal, self, sid,
                                       eio_sid, data, namespace, id)
        else:
            self._handle_event_internal(self, sid, eio_sid, data, namespace,
                                        id)

    def _handle_event_internal(self, server, sid, eio_sid, data, namespace,
                               id):
        r = server._trigger_event(data[0], namespace, sid, *data[1:])
        if r != self.not_handled and id is not None:
            # send ACK packet with the response returned by the handler
            # tuples are expanded as multiple arguments
            if r is None:
                data = []
            elif isinstance(r, tuple):
                data = list(r)
            else:
                data = [r]
            server._send_packet(eio_sid, self.packet_class(
                packet.ACK, namespace=namespace, id=id, data=data))

    def _handle_ack(self, eio_sid, namespace, id, data):
        """Handle ACK packets from the client."""
        namespace = namespace or '/'
        sid = self.manager.sid_from_eio_sid(eio_sid, namespace)
        self.logger.info('received ack from %s [%s]', sid, namespace)
        self.manager.trigger_callback(sid, id, data)

    def _trigger_event(self, event, namespace, *args):
        """Invoke an application event handler."""
        # first see if we have an explicit handler for the event
        handler, args = self._get_event_handler(event, namespace, args)
        if handler:
            try:
                return handler(*args)
            except TypeError:
                # legacy disconnect events use only one argument
                if event == 'disconnect':
                    return handler(*args[:-1])
                else:  # pragma: no cover
                    raise
        # or else, forward the event to a namespace handler if one exists
        handler, args = self._get_namespace_handler(namespace, args)
        if handler:
            return handler.trigger_event(event, *args)
        else:
            return self.not_handled

    def _handle_eio_connect(self, eio_sid, environ):
        """Handle the Engine.IO connection event."""
        if not self.manager_initialized:
            self.manager_initialized = True
            self.manager.initialize()
        self.environ[eio_sid] = environ

    def _handle_eio_message(self, eio_sid, data):
        """Dispatch Engine.IO messages."""
        if eio_sid in self._binary_packet:
            pkt = self._binary_packet[eio_sid]
            if pkt.add_attachment(data):
                del self._binary_packet[eio_sid]
                if pkt.packet_type == packet.BINARY_EVENT:
                    self._handle_event(eio_sid, pkt.namespace, pkt.id,
                                       pkt.data)
                else:
                    self._handle_ack(eio_sid, pkt.namespace, pkt.id, pkt.data)
        else:
            pkt = self.packet_class(encoded_packet=data)
            if pkt.packet_type == packet.CONNECT:
                self._handle_connect(eio_sid, pkt.namespace, pkt.data)
            elif pkt.packet_type == packet.DISCONNECT:
                self._handle_disconnect(eio_sid, pkt.namespace,
                                        self.reason.CLIENT_DISCONNECT)
            elif pkt.packet_type == packet.EVENT:
                self._handle_event(eio_sid, pkt.namespace, pkt.id, pkt.data)
            elif pkt.packet_type == packet.ACK:
                self._handle_ack(eio_sid, pkt.namespace, pkt.id, pkt.data)
            elif pkt.packet_type == packet.BINARY_EVENT or \
                    pkt.packet_type == packet.BINARY_ACK:
                self._binary_packet[eio_sid] = pkt
            elif pkt.packet_type == packet.CONNECT_ERROR:
                raise ValueError('Unexpected CONNECT_ERROR packet.')
            else:
                raise ValueError('Unknown packet type.')

    def _handle_eio_disconnect(self, eio_sid, reason):
        """Handle Engine.IO disconnect event."""
        for n in list(self.manager.get_namespaces()).copy():
            self._handle_disconnect(eio_sid, n, reason)
        if eio_sid in self.environ:
            del self.environ[eio_sid]

    def _engineio_server_class(self):
        return engineio.Server
