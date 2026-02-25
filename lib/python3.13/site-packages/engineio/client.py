from base64 import b64encode
from http.cookies import SimpleCookie
import logging
import queue
import ssl
import threading
import time
import urllib
from engineio.json import JSONDecodeError

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None
try:
    import websocket
except ImportError:  # pragma: no cover
    websocket = None
from . import base_client
from . import exceptions
from . import packet
from . import payload

default_logger = logging.getLogger('engineio.client')


class Client(base_client.BaseClient):
    """An Engine.IO client.

    This class implements a fully compliant Engine.IO web client with support
    for websocket and long-polling transports.

    :param logger: To enable logging set to ``True`` or pass a logger object to
                   use. To disable logging set to ``False``. The default is
                   ``False``. Note that fatal errors are logged even when
                   ``logger`` is ``False``.
    :param json: An alternative JSON module to use for encoding and decoding
                 packets. Custom json modules must have ``dumps`` and ``loads``
                 functions that are compatible with the standard library
                 versions. This is a process-wide setting, all instantiated
                 servers and clients must use the same JSON module.
    :param request_timeout: A timeout in seconds for requests. The default is
                            5 seconds.
    :param http_session: an initialized ``requests.Session`` object to be used
                         when sending requests to the server. Use it if you
                         need to add special client options such as proxy
                         servers, SSL certificates, custom CA bundle, etc.
    :param ssl_verify: ``True`` to verify SSL certificates, or ``False`` to
                       skip SSL certificate verification, allowing
                       connections to servers with self signed certificates.
                       The default is ``True``.
    :param handle_sigint: Set to ``True`` to automatically handle disconnection
                          when the process is interrupted, or to ``False`` to
                          leave interrupt handling to the calling application.
                          Interrupt handling can only be enabled when the
                          client instance is created in the main thread.
    :param websocket_extra_options: Dictionary containing additional keyword
                                    arguments passed to
                                    ``websocket.create_connection()``.
    :param timestamp_requests: If ``True`` a timestamp is added to the query
                               string of Socket.IO requests as a cache-busting
                               measure. Set to ``False`` to disable.
    """
    def connect(self, url, headers=None, transports=None,
                engineio_path='engine.io'):
        """Connect to an Engine.IO server.

        :param url: The URL of the Engine.IO server. It can include custom
                    query string parameters if required by the server.
        :param headers: A dictionary with custom headers to send with the
                        connection request.
        :param transports: The list of allowed transports. Valid transports
                           are ``'polling'`` and ``'websocket'``. If not
                           given, the polling transport is connected first,
                           then an upgrade to websocket is attempted.
        :param engineio_path: The endpoint where the Engine.IO server is
                              installed. The default value is appropriate for
                              most cases.

        Example usage::

            eio = engineio.Client()
            eio.connect('http://localhost:5000')
        """
        if self.state != 'disconnected':
            raise ValueError('Client is not in a disconnected state')
        valid_transports = ['polling', 'websocket']
        if transports is not None:
            if isinstance(transports, str):
                transports = [transports]
            transports = [transport for transport in transports
                          if transport in valid_transports]
            if not transports:
                raise ValueError('No valid transports provided')
        self.transports = transports or valid_transports
        return getattr(self, '_connect_' + self.transports[0])(
            url, headers or {}, engineio_path)

    def wait(self):
        """Wait until the connection with the server ends.

        Client applications can use this function to block the main thread
        during the life of the connection.
        """
        if self.read_loop_task:
            self.read_loop_task.join()

    def send(self, data):
        """Send a message to the server.

        :param data: The data to send to the server. Data can be of type
                     ``str``, ``bytes``, ``list`` or ``dict``. If a ``list``
                     or ``dict``, the data will be serialized as JSON.
        """
        self._send_packet(packet.Packet(packet.MESSAGE, data=data))

    def disconnect(self, abort=False, reason=None):
        """Disconnect from the server.

        :param abort: If set to ``True``, do not wait for background tasks
                      associated with the connection to end.
        """
        if self.state == 'connected':
            self._send_packet(packet.Packet(packet.CLOSE))
            self.queue.put(None)
            self.state = 'disconnecting'
            self._trigger_event('disconnect',
                                reason or self.reason.CLIENT_DISCONNECT,
                                run_async=False)
            if self.current_transport == 'websocket':
                self.ws.close()
            if not abort:
                self.read_loop_task.join()
            self.state = 'disconnected'
            try:
                base_client.connected_clients.remove(self)
            except ValueError:  # pragma: no cover
                pass
        self._reset()

    def start_background_task(self, target, *args, **kwargs):
        """Start a background task.

        This is a utility function that applications can use to start a
        background task.

        :param target: the target function to execute.
        :param args: arguments to pass to the function.
        :param kwargs: keyword arguments to pass to the function.

        This function returns an object that represents the background task,
        on which the ``join()`` method can be invoked to wait for the task to
        complete.
        """
        th = threading.Thread(target=target, args=args, kwargs=kwargs,
                              daemon=True)
        th.start()
        return th

    def sleep(self, seconds=0):
        """Sleep for the requested amount of time."""
        return time.sleep(seconds)

    def create_queue(self, *args, **kwargs):
        """Create a queue object."""
        return queue.Queue(*args, **kwargs)

    def get_queue_empty_exception(self):
        """Return the queue empty exception raised by queues created by the
        ``create_queue()`` method.
        """
        return queue.Empty

    def create_event(self, *args, **kwargs):
        """Create an event object."""
        return threading.Event(*args, **kwargs)

    def _reset(self):
        super()._reset()
        while True:  # pragma: no cover
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except self.queue_empty:
                break

    def _connect_polling(self, url, headers, engineio_path):
        """Establish a long-polling connection to the Engine.IO server."""
        if requests is None:  # pragma: no cover
            # not installed
            self.logger.error('requests package is not installed -- cannot '
                              'send HTTP requests!')
            return
        self.base_url = self._get_engineio_url(url, engineio_path, 'polling')
        self.logger.info('Attempting polling connection to ' + self.base_url)
        r = self._send_request(
            'GET', self.base_url + self._get_url_timestamp(), headers=headers,
            timeout=self.request_timeout)
        if r is None or isinstance(r, str):
            self._reset()
            raise exceptions.ConnectionError(
                r or 'Connection refused by the server')
        if r.status_code < 200 or r.status_code >= 300:
            self._reset()
            try:
                arg = r.json()
            except JSONDecodeError:
                arg = None
            raise exceptions.ConnectionError(
                'Unexpected status code {} in server response'.format(
                    r.status_code), arg)
        try:
            p = payload.Payload(encoded_payload=r.content.decode('utf-8'))
        except ValueError:
            raise exceptions.ConnectionError(
                'Unexpected response from server') from None
        open_packet = p.packets[0]
        if open_packet.packet_type != packet.OPEN:
            raise exceptions.ConnectionError(
                'OPEN packet not returned by server')
        self.logger.info(
            'Polling connection accepted with ' + str(open_packet.data))
        self.sid = open_packet.data['sid']
        self.upgrades = open_packet.data['upgrades']
        self.ping_interval = int(open_packet.data['pingInterval']) / 1000.0
        self.ping_timeout = int(open_packet.data['pingTimeout']) / 1000.0
        self.current_transport = 'polling'
        self.base_url += '&sid=' + self.sid

        self.state = 'connected'
        base_client.connected_clients.append(self)
        self._trigger_event('connect', run_async=False)

        for pkt in p.packets[1:]:
            self._receive_packet(pkt)

        if 'websocket' in self.upgrades and 'websocket' in self.transports:
            # attempt to upgrade to websocket
            if self._connect_websocket(url, headers, engineio_path):
                # upgrade to websocket succeeded, we're done here
                return

        # start background tasks associated with this client
        self.write_loop_task = self.start_background_task(self._write_loop)
        self.read_loop_task = self.start_background_task(
            self._read_loop_polling)

    def _connect_websocket(self, url, headers, engineio_path):
        """Establish or upgrade to a WebSocket connection with the server."""
        if websocket is None:  # pragma: no cover
            # not installed
            self.logger.error('websocket-client package not installed, only '
                              'polling transport is available')
            return False
        websocket_url = self._get_engineio_url(url, engineio_path, 'websocket')
        if self.sid:
            self.logger.info(
                'Attempting WebSocket upgrade to ' + websocket_url)
            upgrade = True
            websocket_url += '&sid=' + self.sid
        else:
            upgrade = False
            self.base_url = websocket_url
            self.logger.info(
                'Attempting WebSocket connection to ' + websocket_url)

        # get cookies and other settings from the long-polling connection
        # so that they are preserved when connecting to the WebSocket route
        cookies = None
        extra_options = {}
        if self.http:
            # cookies
            ck = SimpleCookie()
            for cookie in self.http.cookies:
                ck[cookie.name] = cookie.value
            cookies = ck.output(header='', sep=';').strip()
            for header, value in headers.items():
                if header.lower() == 'cookie':
                    if cookies:
                        cookies += '; '
                    cookies += value
                    del headers[header]
                    break

            # auth
            if 'Authorization' not in headers and self.http.auth is not None:
                if not isinstance(self.http.auth, tuple):  # pragma: no cover
                    raise ValueError('Only basic authentication is supported')
                basic_auth = '{}:{}'.format(
                    self.http.auth[0], self.http.auth[1]).encode('utf-8')
                basic_auth = b64encode(basic_auth).decode('utf-8')
                headers['Authorization'] = 'Basic ' + basic_auth

            # cert
            # this can be given as ('certfile', 'keyfile') or just 'certfile'
            if isinstance(self.http.cert, tuple):
                extra_options['sslopt'] = {
                    'certfile': self.http.cert[0],
                    'keyfile': self.http.cert[1]}
            elif self.http.cert:
                extra_options['sslopt'] = {'certfile': self.http.cert}

            # proxies
            if self.http.proxies:
                proxy_url = None
                if websocket_url.startswith('ws://'):
                    proxy_url = self.http.proxies.get(
                        'ws', self.http.proxies.get('http'))
                else:  # wss://
                    proxy_url = self.http.proxies.get(
                        'wss', self.http.proxies.get('https'))
                if proxy_url:
                    parsed_url = urllib.parse.urlparse(
                        proxy_url if '://' in proxy_url
                        else 'scheme://' + proxy_url)
                    extra_options['http_proxy_host'] = parsed_url.hostname
                    extra_options['http_proxy_port'] = parsed_url.port
                    extra_options['http_proxy_auth'] = (
                        (parsed_url.username, parsed_url.password)
                        if parsed_url.username or parsed_url.password
                        else None)

            # verify
            if isinstance(self.http.verify, str):
                if 'sslopt' in extra_options:
                    extra_options['sslopt']['ca_certs'] = self.http.verify
                else:
                    extra_options['sslopt'] = {'ca_certs': self.http.verify}
            elif not self.http.verify:
                self.ssl_verify = False

        if not self.ssl_verify:
            if 'sslopt' in extra_options:
                extra_options['sslopt'].update({"cert_reqs": ssl.CERT_NONE})
            else:
                extra_options['sslopt'] = {"cert_reqs": ssl.CERT_NONE}

        # combine internally generated options with the ones supplied by the
        # caller. The caller's options take precedence.
        headers.update(self.websocket_extra_options.pop('header', {}))
        extra_options['header'] = headers
        extra_options['cookie'] = cookies
        extra_options['enable_multithread'] = True
        extra_options['timeout'] = self.request_timeout
        extra_options.update(self.websocket_extra_options)
        try:
            ws = websocket.create_connection(
                websocket_url + self._get_url_timestamp(), **extra_options)
        except (ConnectionError, OSError, websocket.WebSocketException):
            if upgrade:
                self.logger.warning(
                    'WebSocket upgrade failed: connection error')
                return False
            else:
                raise exceptions.ConnectionError('Connection error')
        if upgrade:
            p = packet.Packet(packet.PING, data='probe').encode()
            try:
                ws.send(p)
            except Exception as e:  # pragma: no cover
                self.logger.warning(
                    'WebSocket upgrade failed: unexpected send exception: %s',
                    str(e))
                return False
            try:
                p = ws.recv()
            except Exception as e:  # pragma: no cover
                self.logger.warning(
                    'WebSocket upgrade failed: unexpected recv exception: %s',
                    str(e))
                return False
            pkt = packet.Packet(encoded_packet=p)
            if pkt.packet_type != packet.PONG or pkt.data != 'probe':
                self.logger.warning(
                    'WebSocket upgrade failed: no PONG packet')
                return False
            p = packet.Packet(packet.UPGRADE).encode()
            try:
                ws.send(p)
            except Exception as e:  # pragma: no cover
                self.logger.warning(
                    'WebSocket upgrade failed: unexpected send exception: %s',
                    str(e))
                return False
            self.current_transport = 'websocket'
            self.logger.info('WebSocket upgrade was successful')
        else:
            try:
                p = ws.recv()
            except Exception as e:  # pragma: no cover
                raise exceptions.ConnectionError(
                    'Unexpected recv exception: ' + str(e))
            open_packet = packet.Packet(encoded_packet=p)
            if open_packet.packet_type != packet.OPEN:
                raise exceptions.ConnectionError('no OPEN packet')
            self.logger.info(
                'WebSocket connection accepted with ' + str(open_packet.data))
            self.sid = open_packet.data['sid']
            self.upgrades = open_packet.data['upgrades']
            self.ping_interval = int(open_packet.data['pingInterval']) / 1000.0
            self.ping_timeout = int(open_packet.data['pingTimeout']) / 1000.0
            self.current_transport = 'websocket'

            self.state = 'connected'
            base_client.connected_clients.append(self)
            self._trigger_event('connect', run_async=False)
        self.ws = ws
        self.ws.settimeout(self.ping_interval + self.ping_timeout)

        # start background tasks associated with this client
        self.write_loop_task = self.start_background_task(self._write_loop)
        self.read_loop_task = self.start_background_task(
            self._read_loop_websocket)
        return True

    def _receive_packet(self, pkt):
        """Handle incoming packets from the server."""
        packet_name = packet.packet_names[pkt.packet_type] \
            if pkt.packet_type < len(packet.packet_names) else 'UNKNOWN'
        self.logger.info(
            'Received packet %s data %s', packet_name,
            pkt.data if not isinstance(pkt.data, bytes) else '<binary>')
        if pkt.packet_type == packet.MESSAGE:
            self._trigger_event('message', pkt.data, run_async=True)
        elif pkt.packet_type == packet.PING:
            self._send_packet(packet.Packet(packet.PONG, pkt.data))
        elif pkt.packet_type == packet.CLOSE:
            self.disconnect(abort=True, reason=self.reason.SERVER_DISCONNECT)
        elif pkt.packet_type == packet.NOOP:
            pass
        else:
            self.logger.error('Received unexpected packet of type %s',
                              pkt.packet_type)

    def _send_packet(self, pkt):
        """Queue a packet to be sent to the server."""
        if self.state != 'connected':
            return
        self.queue.put(pkt)
        self.logger.info(
            'Sending packet %s data %s',
            packet.packet_names[pkt.packet_type],
            pkt.data if not isinstance(pkt.data, bytes) else '<binary>')

    def _send_request(
            self, method, url, headers=None, body=None,
            timeout=None):  # pragma: no cover
        if self.http is None:
            self.http = requests.Session()
        if not self.ssl_verify:
            self.http.verify = False
        try:
            return self.http.request(method, url, headers=headers, data=body,
                                     timeout=timeout)
        except requests.exceptions.RequestException as exc:
            self.logger.info('HTTP %s request to %s failed with error %s.',
                             method, url, exc)
            return str(exc)

    def _trigger_event(self, event, *args, **kwargs):
        """Invoke an event handler."""
        run_async = kwargs.pop('run_async', False)
        if event in self.handlers:
            if run_async:
                return self.start_background_task(self.handlers[event], *args)
            else:
                try:
                    try:
                        return self.handlers[event](*args)
                    except TypeError:
                        if event == 'disconnect' and \
                                len(args) == 1:  # pragma: no branch
                            # legacy disconnect events do  not have a reason
                            # argument
                            return self.handlers[event]()
                        else:  # pragma: no cover
                            raise
                except:
                    self.logger.exception(event + ' handler error')

    def _read_loop_polling(self):
        """Read packets by polling the Engine.IO server."""
        while self.state == 'connected' and self.write_loop_task:
            self.logger.info(
                'Sending polling GET request to ' + self.base_url)
            r = self._send_request(
                'GET', self.base_url + self._get_url_timestamp(),
                timeout=max(self.ping_interval, self.ping_timeout) + 5)
            if r is None or isinstance(r, str):
                self.logger.warning(
                    r or 'Connection refused by the server, aborting')
                self.queue.put(None)
                break
            if r.status_code < 200 or r.status_code >= 300:
                self.logger.warning('Unexpected status code %s in server '
                                    'response, aborting', r.status_code)
                self.queue.put(None)
                break
            try:
                p = payload.Payload(encoded_payload=r.content.decode('utf-8'))
            except ValueError:
                self.logger.warning(
                    'Unexpected packet from server, aborting')
                self.queue.put(None)
                break
            for pkt in p.packets:
                self._receive_packet(pkt)

        if self.write_loop_task:  # pragma: no branch
            self.logger.info('Waiting for write loop task to end')
            self.write_loop_task.join()
        if self.state == 'connected':
            self._trigger_event('disconnect', self.reason.TRANSPORT_ERROR,
                                run_async=False)
            try:
                base_client.connected_clients.remove(self)
            except ValueError:  # pragma: no cover
                pass
            self._reset()
        self.logger.info('Exiting read loop task')

    def _read_loop_websocket(self):
        """Read packets from the Engine.IO WebSocket connection."""
        while self.state == 'connected':
            p = None
            try:
                p = self.ws.recv()
                if len(p) == 0 and not self.ws.connected:  # pragma: no cover
                    # websocket client can return an empty string after close
                    raise websocket.WebSocketConnectionClosedException()
            except websocket.WebSocketTimeoutException:
                self.logger.warning(
                    'Server has stopped communicating, aborting')
                self.queue.put(None)
                break
            except websocket.WebSocketConnectionClosedException:
                self.logger.warning(
                    'WebSocket connection was closed, aborting')
                self.queue.put(None)
                break
            except Exception as e:  # pragma: no cover
                if type(e) is OSError and e.errno == 9:
                    self.logger.info(
                        'WebSocket connection is closing, aborting')
                else:
                    self.logger.info(
                        'Unexpected error receiving packet: "%s", aborting',
                        str(e))
                self.queue.put(None)
                break
            try:
                pkt = packet.Packet(encoded_packet=p)
            except Exception as e:  # pragma: no cover
                self.logger.info(
                    'Unexpected error decoding packet: "%s", aborting', str(e))
                self.queue.put(None)
                break
            self._receive_packet(pkt)

        if self.write_loop_task:  # pragma: no branch
            self.logger.info('Waiting for write loop task to end')
            self.write_loop_task.join()
        if self.state == 'connected':
            self._trigger_event('disconnect', self.reason.TRANSPORT_ERROR,
                                run_async=False)
            try:
                base_client.connected_clients.remove(self)
            except ValueError:  # pragma: no cover
                pass
            self._reset()
        self.logger.info('Exiting read loop task')

    def _write_loop(self):
        """This background task sends packages to the server as they are
        pushed to the send queue.
        """
        while self.state == 'connected':
            # to simplify the timeout handling, use the maximum of the
            # ping interval and ping timeout as timeout, with an extra 5
            # seconds grace period
            timeout = max(self.ping_interval, self.ping_timeout) + 5
            packets = None
            try:
                packets = [self.queue.get(timeout=timeout)]
            except self.queue_empty:
                self.logger.error('packet queue is empty, aborting')
                break
            if packets == [None]:
                self.queue.task_done()
                packets = []
            else:
                while True:
                    try:
                        packets.append(self.queue.get(block=False))
                    except self.queue_empty:
                        break
                    if packets[-1] is None:
                        packets = packets[:-1]
                        self.queue.task_done()
                        break
            if not packets:
                # empty packet list returned -> connection closed
                break
            if self.current_transport == 'polling':
                p = payload.Payload(packets=packets)
                r = self._send_request(
                    'POST', self.base_url, body=p.encode(),
                    headers={'Content-Type': 'text/plain'},
                    timeout=self.request_timeout)
                for pkt in packets:
                    self.queue.task_done()
                if r is None or isinstance(r, str):
                    self.logger.warning(
                        r or 'Connection refused by the server, aborting')
                    break
                if r.status_code < 200 or r.status_code >= 300:
                    self.logger.warning('Unexpected status code %s in server '
                                        'response, aborting', r.status_code)
                    self.write_loop_task = None
                    break
            else:
                # websocket
                try:
                    for pkt in packets:
                        encoded_packet = pkt.encode()
                        if pkt.binary:
                            self.ws.send_binary(encoded_packet)
                        else:
                            self.ws.send(encoded_packet)
                        self.queue.task_done()
                except (websocket.WebSocketConnectionClosedException,
                        BrokenPipeError, OSError):
                    self.logger.warning(
                        'WebSocket connection was closed, aborting')
                    break
        self.logger.info('Exiting write loop task')
