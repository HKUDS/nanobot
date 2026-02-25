import logging
import urllib

from . import base_server
from . import exceptions
from . import packet
from . import socket

default_logger = logging.getLogger('engineio.server')


class Server(base_server.BaseServer):
    """An Engine.IO server.

    This class implements a fully compliant Engine.IO web server with support
    for websocket and long-polling transports.

    :param async_mode: The asynchronous model to use. See the Deployment
                       section in the documentation for a description of the
                       available options. Valid async modes are "threading",
                       "eventlet", "gevent" and "gevent_uwsgi". If this
                       argument is not given, "eventlet" is tried first, then
                       "gevent_uwsgi", then "gevent", and finally "threading".
                       The first async mode that has all its dependencies
                       installed is the one that is chosen.
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
                   server sends back tot he client containing the client
                   session id. If set to a dictionary, the ``'name'`` key
                   contains the cookie name and other keys define cookie
                   attributes, where the value of each attribute can be a
                   string, a callable with no arguments, or a boolean. If set
                   to ``None`` (the default), a cookie is not sent to the
                   client.
    :param cors_allowed_origins: Origin or list of origins that are allowed to
                                 connect to this server. Only the same origin
                                 is allowed by default. Set this argument to
                                 ``'*'`` or ``['*']`` to allow all origins, or
                                 to ``[]`` to disable CORS handling.
    :param cors_credentials: Whether credentials (cookies, authentication) are
                             allowed in requests to this server. The default
                             is ``True``.
    :param logger: To enable logging set to ``True`` or pass a logger object to
                   use. To disable logging set to ``False``. The default is
                   ``False``. Note that fatal errors are logged even when
                   ``logger`` is ``False``.
    :param json: An alternative JSON module to use for encoding and decoding
                 packets. Custom JSON modules must have ``dumps`` and ``loads``
                 functions that are compatible with the standard library
                 versions. This is a process-wide setting, all instantiated
                 servers and clients must use the same JSON module.
    :param async_handlers: If set to ``True``, run message event handlers in
                           non-blocking threads. To run handlers synchronously,
                           set to ``False``. The default is ``True``.
    :param monitor_clients: If set to ``True``, a background task will ensure
                            inactive clients are closed. Set to ``False`` to
                            disable the monitoring task (not recommended). The
                            default is ``True``.
    :param transports: The list of allowed transports. Valid transports
                       are ``'polling'`` and ``'websocket'``. Defaults to
                       ``['polling', 'websocket']``.
    :param kwargs: Reserved for future extensions, any additional parameters
                   given as keyword arguments will be silently ignored.
    """
    def send(self, sid, data):
        """Send a message to a client.

        :param sid: The session id of the recipient client.
        :param data: The data to send to the client. Data can be of type
                     ``str``, ``bytes``, ``list`` or ``dict``. If a ``list``
                     or ``dict``, the data will be serialized as JSON.
        """
        self.send_packet(sid, packet.Packet(packet.MESSAGE, data=data))

    def send_packet(self, sid, pkt):
        """Send a raw packet to a client.

        :param sid: The session id of the recipient client.
        :param pkt: The packet to send to the client.
        """
        try:
            socket = self._get_socket(sid)
        except KeyError:
            # the socket is not available
            self.logger.warning('Cannot send to sid %s', sid)
            return
        socket.send(pkt)

    def get_session(self, sid):
        """Return the user session for a client.

        :param sid: The session id of the client.

        The return value is a dictionary. Modifications made to this
        dictionary are not guaranteed to be preserved unless
        ``save_session()`` is called, or when the ``session`` context manager
        is used.
        """
        socket = self._get_socket(sid)
        return socket.session

    def save_session(self, sid, session):
        """Store the user session for a client.

        :param sid: The session id of the client.
        :param session: The session dictionary.
        """
        socket = self._get_socket(sid)
        socket.session = session

    def session(self, sid):
        """Return the user session for a client with context manager syntax.

        :param sid: The session id of the client.

        This is a context manager that returns the user session dictionary for
        the client. Any changes that are made to this dictionary inside the
        context manager block are saved back to the session. Example usage::

            @eio.on('connect')
            def on_connect(sid, environ):
                username = authenticate_user(environ)
                if not username:
                    return False
                with eio.session(sid) as session:
                    session['username'] = username

            @eio.on('message')
            def on_message(sid, msg):
                with eio.session(sid) as session:
                    print('received message from ', session['username'])
        """
        class _session_context_manager:
            def __init__(self, server, sid):
                self.server = server
                self.sid = sid
                self.session = None

            def __enter__(self):
                self.session = self.server.get_session(sid)
                return self.session

            def __exit__(self, *args):
                self.server.save_session(sid, self.session)

        return _session_context_manager(self, sid)

    def disconnect(self, sid=None):
        """Disconnect a client.

        :param sid: The session id of the client to close. If this parameter
                    is not given, then all clients are closed.
        """
        if sid is not None:
            try:
                socket = self._get_socket(sid)
            except KeyError:  # pragma: no cover
                # the socket was already closed or gone
                pass
            else:
                socket.close(reason=self.reason.SERVER_DISCONNECT)
                if sid in self.sockets:  # pragma: no cover
                    del self.sockets[sid]
        else:
            for client in self.sockets.copy().values():
                client.close(reason=self.reason.SERVER_DISCONNECT)
            self.sockets = {}

    def handle_request(self, environ, start_response):
        """Handle an HTTP request from the client.

        This is the entry point of the Engine.IO application, using the same
        interface as a WSGI application. For the typical usage, this function
        is invoked by the :class:`Middleware` instance, but it can be invoked
        directly when the middleware is not used.

        :param environ: The WSGI environment.
        :param start_response: The WSGI ``start_response`` function.

        This function returns the HTTP response body to deliver to the client
        as a byte sequence.
        """
        if self.cors_allowed_origins != []:
            # Validate the origin header if present
            # This is important for WebSocket more than for HTTP, since
            # browsers only apply CORS controls to HTTP.
            origin = environ.get('HTTP_ORIGIN')
            if origin:
                allowed_origins = self._cors_allowed_origins(environ)
                if allowed_origins is not None and origin not in \
                        allowed_origins:
                    self._log_error_once(
                        origin + ' is not an accepted origin.', 'bad-origin')
                    r = self._bad_request('Not an accepted origin.')
                    start_response(r['status'], r['headers'])
                    return [r['response']]

        method = environ['REQUEST_METHOD']
        query = urllib.parse.parse_qs(environ.get('QUERY_STRING', ''))
        jsonp = False
        jsonp_index = None

        # make sure the client uses an allowed transport
        transport = query.get('transport', ['polling'])[0]
        if transport not in self.transports:
            self._log_error_once('Invalid transport', 'bad-transport')
            r = self._bad_request('Invalid transport')
            start_response(r['status'], r['headers'])
            return [r['response']]

        # make sure the client speaks a compatible Engine.IO version
        sid = query['sid'][0] if 'sid' in query else None
        if sid is None and query.get('EIO') != ['4']:
            self._log_error_once(
                'The client is using an unsupported version of the Socket.IO '
                'or Engine.IO protocols', 'bad-version')
            r = self._bad_request(
                'The client is using an unsupported version of the Socket.IO '
                'or Engine.IO protocols')
            start_response(r['status'], r['headers'])
            return [r['response']]

        if 'j' in query:
            jsonp = True
            try:
                jsonp_index = int(query['j'][0])
            except (ValueError, KeyError, IndexError):
                # Invalid JSONP index number
                pass

        if jsonp and jsonp_index is None:
            self._log_error_once('Invalid JSONP index number',
                                 'bad-jsonp-index')
            r = self._bad_request('Invalid JSONP index number')
        elif method == 'GET':
            upgrade_header = environ.get('HTTP_UPGRADE').lower() \
                if 'HTTP_UPGRADE' in environ else None
            if sid is None:
                # transport must be one of 'polling' or 'websocket'.
                # if 'websocket', the HTTP_UPGRADE header must match.
                if transport == 'polling' \
                        or transport == upgrade_header == 'websocket':
                    r = self._handle_connect(environ, start_response,
                                             transport, jsonp_index)
                else:
                    self._log_error_once('Invalid websocket upgrade',
                                         'bad-upgrade')
                    r = self._bad_request('Invalid websocket upgrade')
            else:
                if sid not in self.sockets:
                    self._log_error_once(f'Invalid session {sid}', 'bad-sid')
                    r = self._bad_request(f'Invalid session {sid}')
                else:
                    try:
                        socket = self._get_socket(sid)
                    except KeyError as e:  # pragma: no cover
                        self._log_error_once(f'{e} {sid}', 'bad-sid')
                        r = self._bad_request(f'{e} {sid}')
                    else:
                        if self.transport(sid) != transport and \
                                transport != upgrade_header:
                            self._log_error_once(
                                f'Invalid transport for session {sid}',
                                'bad-transport')
                            r = self._bad_request('Invalid transport')
                        else:
                            try:
                                packets = socket.handle_get_request(
                                    environ, start_response)
                                if isinstance(packets, list):
                                    r = self._ok(packets,
                                                 jsonp_index=jsonp_index)
                                else:
                                    r = packets
                            except exceptions.EngineIOError:
                                if sid in self.sockets:  # pragma: no cover
                                    self.disconnect(sid)
                                r = self._bad_request()
                            if sid in self.sockets and \
                                    self.sockets[sid].closed:
                                del self.sockets[sid]
        elif method == 'POST':
            if sid is None or sid not in self.sockets:
                self._log_error_once(f'Invalid session {sid}', 'bad-sid')
                r = self._bad_request(f'Invalid session {sid}')
            else:
                socket = self._get_socket(sid)
                try:
                    socket.handle_post_request(environ)
                    r = self._ok(jsonp_index=jsonp_index)
                except exceptions.EngineIOError:
                    if sid in self.sockets:  # pragma: no cover
                        self.disconnect(sid)
                    r = self._bad_request()
                except:  # pragma: no cover
                    # for any other unexpected errors, we log the error
                    # and keep going
                    self.logger.exception('post request handler error')
                    r = self._ok(jsonp_index=jsonp_index)
        elif method == 'OPTIONS':
            r = self._ok()
        else:
            self.logger.warning('Method %s not supported', method)
            r = self._method_not_found()

        if not isinstance(r, dict):
            return r
        if self.http_compression and \
                len(r['response']) >= self.compression_threshold:
            encodings = [e.split(';')[0].strip() for e in
                         environ.get('HTTP_ACCEPT_ENCODING', '').split(',')]
            for encoding in encodings:
                if encoding in self.compression_methods:
                    r['response'] = \
                        getattr(self, '_' + encoding)(r['response'])
                    r['headers'] += [('Content-Encoding', encoding)]
                    break
        cors_headers = self._cors_headers(environ)
        start_response(r['status'], r['headers'] + cors_headers)
        return [r['response']]

    def shutdown(self):
        """Stop Socket.IO background tasks.

        This method stops background activity initiated by the Socket.IO
        server. It must be called before shutting down the web server.
        """
        self.logger.info('Socket.IO is shutting down')
        if self.service_task_event:  # pragma: no cover
            self.service_task_event.set()
            self.service_task_handle.join()
            self.service_task_handle = None

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
        th = self._async['thread'](target=target, args=args, kwargs=kwargs)
        th.start()
        return th  # pragma: no cover

    def sleep(self, seconds=0):
        """Sleep for the requested amount of time using the appropriate async
        model.

        This is a utility function that applications can use to put a task to
        sleep without having to worry about using the correct call for the
        selected async mode.
        """
        return self._async['sleep'](seconds)

    def _handle_connect(self, environ, start_response, transport,
                        jsonp_index=None):
        """Handle a client connection request."""
        if self.start_service_task:
            # start the service task to monitor connected clients
            self.start_service_task = False
            self.service_task_handle = self.start_background_task(
                self._service_task)

        sid = self.generate_id()
        s = socket.Socket(self, sid)
        self.sockets[sid] = s

        pkt = packet.Packet(packet.OPEN, {
            'sid': sid,
            'upgrades': self._upgrades(sid, transport),
            'pingTimeout': int(self.ping_timeout * 1000),
            'pingInterval': int(
                self.ping_interval + self.ping_interval_grace_period) * 1000,
            'maxPayload': self.max_http_buffer_size,
        })
        s.send(pkt)
        s.schedule_ping()

        # NOTE: some sections below are marked as "no cover" to workaround
        # what seems to be a bug in the coverage package. All the lines below
        # are covered by tests, but some are not reported as such for some
        # reason
        ret = self._trigger_event('connect', sid, environ, run_async=False)
        if ret is not None and ret is not True:  # pragma: no cover
            del self.sockets[sid]
            self.logger.warning('Application rejected connection')
            return self._unauthorized(ret or None)

        if transport == 'websocket':  # pragma: no cover
            ret = s.handle_get_request(environ, start_response)
            if s.closed and sid in self.sockets:
                # websocket connection ended, so we are done
                del self.sockets[sid]
            return ret
        else:  # pragma: no cover
            s.connected = True
            headers = None
            if self.cookie:
                if isinstance(self.cookie, dict):
                    headers = [(
                        'Set-Cookie',
                        self._generate_sid_cookie(sid, self.cookie)
                    )]
                else:
                    headers = [(
                        'Set-Cookie',
                        self._generate_sid_cookie(sid, {
                            'name': self.cookie, 'path': '/', 'SameSite': 'Lax'
                        })
                    )]
            try:
                return self._ok(s.poll(), headers=headers,
                                jsonp_index=jsonp_index)
            except exceptions.QueueEmpty:
                return self._bad_request()

    def _trigger_event(self, event, *args, **kwargs):
        """Invoke an event handler."""
        run_async = kwargs.pop('run_async', False)
        if event in self.handlers:
            def run_handler():
                try:
                    try:
                        return self.handlers[event](*args)
                    except TypeError:
                        if event == 'disconnect' and \
                                len(args) == 2:  # pragma: no branch
                            # legacy disconnect events do not have a reason
                            # argument
                            return self.handlers[event](args[0])
                        else:  # pragma: no cover
                            raise
                except:
                    self.logger.exception(event + ' handler error')
                    if event == 'connect':
                        # if connect handler raised error we reject the
                        # connection
                        return False

            if run_async:
                return self.start_background_task(run_handler)
            else:
                return run_handler()

    def _service_task(self):  # pragma: no cover
        """Monitor connected clients and clean up those that time out."""
        self.service_task_event = self.create_event()
        while not self.service_task_event.is_set():
            if len(self.sockets) == 0:
                # nothing to do
                if self.service_task_event.wait(timeout=self.ping_timeout):
                    break
                continue

            # go through the entire client list in a ping interval cycle
            sleep_interval = float(self.ping_timeout) / len(self.sockets)

            try:
                # iterate over the current clients
                for s in self.sockets.copy().values():
                    if s.closed:
                        try:
                            del self.sockets[s.sid]
                        except KeyError:
                            # the socket could have also been removed by
                            # the _get_socket() method from another thread
                            pass
                    elif not s.closing:
                        s.check_ping_timeout()
                    if self.service_task_event.wait(timeout=sleep_interval):
                        raise KeyboardInterrupt()
            except (SystemExit, KeyboardInterrupt):
                self.logger.info('service task canceled')
                break
            except:
                # an unexpected exception has occurred, log it and continue
                self.logger.exception('service task exception')
