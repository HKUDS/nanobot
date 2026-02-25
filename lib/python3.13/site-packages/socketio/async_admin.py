import asyncio
from datetime import datetime, timezone
import functools
import inspect
import os
import socket
import time
from urllib.parse import parse_qs
from .admin import EventBuffer
from .exceptions import ConnectionRefusedError

HOSTNAME = socket.gethostname()
PID = os.getpid()


class InstrumentedAsyncServer:
    def __init__(self, sio, auth=None, namespace='/admin', read_only=False,
                 server_id=None, mode='development', server_stats_interval=2):
        """Instrument the Socket.IO server for monitoring with the `Socket.IO
        Admin UI <https://socket.io/docs/v4/admin-ui/>`_.
        """
        if auth is None:
            raise ValueError('auth must be specified')
        self.sio = sio
        self.auth = auth
        self.admin_namespace = namespace
        self.read_only = read_only
        self.server_id = server_id or (
            self.sio.manager.host_id if hasattr(self.sio.manager, 'host_id')
            else HOSTNAME
        )
        self.mode = mode
        self.server_stats_interval = server_stats_interval
        self.admin_queue = []
        self.event_buffer = EventBuffer()

        # task that emits "server_stats" every 2 seconds
        self.stop_stats_event = None
        self.stats_task = None

        # monkey-patch the server to report metrics to the admin UI
        self.instrument()

    def instrument(self):
        self.sio.on('connect', self.admin_connect,
                    namespace=self.admin_namespace)

        if self.mode == 'development':
            if not self.read_only:  # pragma: no branch
                self.sio.on('emit', self.admin_emit,
                            namespace=self.admin_namespace)
                self.sio.on('join', self.admin_enter_room,
                            namespace=self.admin_namespace)
                self.sio.on('leave', self.admin_leave_room,
                            namespace=self.admin_namespace)
                self.sio.on('_disconnect', self.admin_disconnect,
                            namespace=self.admin_namespace)

            # track socket connection times
            self.sio.manager._timestamps = {}

            # report socket.io connections, disconnections and received events
            self.sio.__trigger_event = self.sio._trigger_event
            self.sio._trigger_event = self._trigger_event

            # report join rooms
            self.sio.manager.__basic_enter_room = \
                self.sio.manager.basic_enter_room
            self.sio.manager.basic_enter_room = self._basic_enter_room

            # report leave rooms
            self.sio.manager.__basic_leave_room = \
                self.sio.manager.basic_leave_room
            self.sio.manager.basic_leave_room = self._basic_leave_room

            # report emit events
            self.sio.manager.__emit = self.sio.manager.emit
            self.sio.manager.emit = self._emit

        # report engine.io connections
        self.sio.eio.on('connect', self._handle_eio_connect)
        self.sio.eio.on('disconnect', self._handle_eio_disconnect)

        # report polling packets
        from engineio.async_socket import AsyncSocket
        self.sio.eio.__ok = self.sio.eio._ok
        self.sio.eio._ok = self._eio_http_response
        AsyncSocket.__handle_post_request = AsyncSocket.handle_post_request
        AsyncSocket.handle_post_request = functools.partialmethod(
            self.__class__._eio_handle_post_request, self)

        # report websocket packets
        AsyncSocket.__websocket_handler = AsyncSocket._websocket_handler
        AsyncSocket._websocket_handler = functools.partialmethod(
            self.__class__._eio_websocket_handler, self)

        # report connected sockets with each ping
        if self.mode == 'development':
            AsyncSocket.__send_ping = AsyncSocket._send_ping
            AsyncSocket._send_ping = functools.partialmethod(
                self.__class__._eio_send_ping, self)

    def uninstrument(self):  # pragma: no cover
        if self.mode == 'development':
            self.sio._trigger_event = self.sio.__trigger_event
            self.sio.manager.basic_enter_room = \
                self.sio.manager.__basic_enter_room
            self.sio.manager.basic_leave_room = \
                self.sio.manager.__basic_leave_room
            self.sio.manager.emit = self.sio.manager.__emit
        self.sio.eio._ok = self.sio.eio.__ok

        from engineio.async_socket import AsyncSocket
        AsyncSocket.handle_post_request = AsyncSocket.__handle_post_request
        AsyncSocket._websocket_handler = AsyncSocket.__websocket_handler
        if self.mode == 'development':
            AsyncSocket._send_ping = AsyncSocket.__send_ping

    async def admin_connect(self, sid, environ, client_auth):
        authenticated = True
        if self.auth:
            authenticated = False
            if isinstance(self.auth, dict):
                authenticated = client_auth == self.auth
            elif isinstance(self.auth, list):
                authenticated = client_auth in self.auth
            else:
                if inspect.iscoroutinefunction(self.auth):
                    authenticated = await self.auth(client_auth)
                else:
                    authenticated = self.auth(client_auth)
            if not authenticated:
                raise ConnectionRefusedError('authentication failed')

        async def config(sid):
            await self.sio.sleep(0.1)

            # supported features
            features = ['AGGREGATED_EVENTS']
            if not self.read_only:
                features += ['EMIT', 'JOIN', 'LEAVE', 'DISCONNECT', 'MJOIN',
                             'MLEAVE', 'MDISCONNECT']
            if self.mode == 'development':
                features.append('ALL_EVENTS')
            await self.sio.emit('config', {'supportedFeatures': features},
                                to=sid, namespace=self.admin_namespace)

            # send current sockets
            if self.mode == 'development':
                all_sockets = []
                for nsp in self.sio.manager.get_namespaces():
                    for sid, eio_sid in self.sio.manager.get_participants(
                            nsp, None):
                        all_sockets.append(
                            self.serialize_socket(sid, nsp, eio_sid))
                await self.sio.emit('all_sockets', all_sockets, to=sid,
                                    namespace=self.admin_namespace)

        self.sio.start_background_task(config, sid)

    async def admin_emit(self, _, namespace, room_filter, event, *data):
        await self.sio.emit(event, data, to=room_filter, namespace=namespace)

    async def admin_enter_room(self, _, namespace, room, room_filter=None):
        for sid, _ in self.sio.manager.get_participants(
                namespace, room_filter):
            await self.sio.enter_room(sid, room, namespace=namespace)

    async def admin_leave_room(self, _, namespace, room, room_filter=None):
        for sid, _ in self.sio.manager.get_participants(
                namespace, room_filter):
            await self.sio.leave_room(sid, room, namespace=namespace)

    async def admin_disconnect(self, _, namespace, close, room_filter=None):
        for sid, _ in self.sio.manager.get_participants(
                namespace, room_filter):
            await self.sio.disconnect(sid, namespace=namespace)

    async def shutdown(self):
        if self.stats_task:  # pragma: no branch
            self.stop_stats_event.set()
            await asyncio.gather(self.stats_task)
            self.stats_task = None
            self.stop_stats_event.clear()

    async def _trigger_event(self, event, namespace, *args):
        t = time.time()
        sid = args[0]
        if event == 'connect':
            eio_sid = self.sio.manager.eio_sid_from_sid(sid, namespace)
            self.sio.manager._timestamps[sid] = t
            serialized_socket = self.serialize_socket(sid, namespace, eio_sid)
            await self.sio.emit('socket_connected', (
                serialized_socket,
                datetime.fromtimestamp(t, timezone.utc).isoformat(),
            ), namespace=self.admin_namespace)
            if not self.sio.eio._get_socket(eio_sid).upgraded:
                self.sio.start_background_task(
                    self._check_for_upgrade, eio_sid, sid, namespace)
        elif event == 'disconnect':
            del self.sio.manager._timestamps[sid]
            reason = args[1]
            await self.sio.emit('socket_disconnected', (
                namespace,
                sid,
                reason,
                datetime.fromtimestamp(t, timezone.utc).isoformat(),
            ), namespace=self.admin_namespace)
        else:
            await self.sio.emit('event_received', (
                namespace,
                sid,
                (event, *args[1:]),
                datetime.fromtimestamp(t, timezone.utc).isoformat(),
            ), namespace=self.admin_namespace)
        return await self.sio.__trigger_event(event, namespace, *args)

    async def _check_for_upgrade(self, eio_sid, sid,
                                 namespace):  # pragma: no cover
        for _ in range(5):
            await self.sio.sleep(5)
            try:
                if self.sio.eio._get_socket(eio_sid).upgraded:
                    await self.sio.emit('socket_updated', {
                        'id': sid,
                        'nsp': namespace,
                        'transport': 'websocket',
                    }, namespace=self.admin_namespace)
                    break
            except KeyError:
                pass

    def _basic_enter_room(self, sid, namespace, room, eio_sid=None):
        ret = self.sio.manager.__basic_enter_room(sid, namespace, room,
                                                  eio_sid)
        if room:
            self.admin_queue.append(('room_joined', (
                namespace,
                room,
                sid,
                datetime.now(timezone.utc).isoformat(),
            )))
        return ret

    def _basic_leave_room(self, sid, namespace, room):
        if room:
            self.admin_queue.append(('room_left', (
                namespace,
                room,
                sid,
                datetime.now(timezone.utc).isoformat(),
            )))
        return self.sio.manager.__basic_leave_room(sid, namespace, room)

    async def _emit(self, event, data, namespace, room=None, skip_sid=None,
                    callback=None, **kwargs):
        ret = await self.sio.manager.__emit(
            event, data, namespace, room=room, skip_sid=skip_sid,
            callback=callback, **kwargs)
        if namespace != self.admin_namespace:
            event_data = [event] + list(data) if isinstance(data, tuple) \
                else [event, data]
            if not isinstance(skip_sid, list):  # pragma: no branch
                skip_sid = [skip_sid]
            for sid, _ in self.sio.manager.get_participants(namespace, room):
                if sid not in skip_sid:
                    await self.sio.emit('event_sent', (
                        namespace,
                        sid,
                        event_data,
                        datetime.now(timezone.utc).isoformat(),
                    ), namespace=self.admin_namespace)
        return ret

    async def _handle_eio_connect(self, eio_sid, environ):
        if self.stop_stats_event is None:
            self.stop_stats_event = self.sio.eio.create_event()
        if self.stats_task is None:
            self.stats_task = self.sio.start_background_task(
                self._emit_server_stats)

        self.event_buffer.push('rawConnection')
        return await self.sio._handle_eio_connect(eio_sid, environ)

    async def _handle_eio_disconnect(self, eio_sid, reason):
        self.event_buffer.push('rawDisconnection')
        return await self.sio._handle_eio_disconnect(eio_sid, reason)

    def _eio_http_response(self, packets=None, headers=None, jsonp_index=None):
        ret = self.sio.eio.__ok(packets=packets, headers=headers,
                                jsonp_index=jsonp_index)
        self.event_buffer.push('packetsOut')
        self.event_buffer.push('bytesOut', len(ret['response']))
        return ret

    async def _eio_handle_post_request(socket, self, environ):
        ret = await socket.__handle_post_request(environ)
        self.event_buffer.push('packetsIn')
        self.event_buffer.push(
            'bytesIn', int(environ.get('CONTENT_LENGTH', 0)))
        return ret

    async def _eio_websocket_handler(socket, self, ws):
        async def _send(ws, data):
            self.event_buffer.push('packetsOut')
            self.event_buffer.push('bytesOut', len(data))
            return await ws.__send(data)

        async def _wait(ws):
            ret = await ws.__wait()
            self.event_buffer.push('packetsIn')
            self.event_buffer.push('bytesIn', len(ret or ''))
            return ret

        ws.__send = ws.send
        ws.send = functools.partial(_send, ws)
        ws.__wait = ws.wait
        ws.wait = functools.partial(_wait, ws)
        return await socket.__websocket_handler(ws)

    async def _eio_send_ping(socket, self):  # pragma: no cover
        eio_sid = socket.sid
        t = time.time()
        for namespace in self.sio.manager.get_namespaces():
            sid = self.sio.manager.sid_from_eio_sid(eio_sid, namespace)
            if sid:
                serialized_socket = self.serialize_socket(sid, namespace,
                                                          eio_sid)
                await self.sio.emit('socket_connected', (
                    serialized_socket,
                    datetime.fromtimestamp(t, timezone.utc).isoformat(),
                ), namespace=self.admin_namespace)
        return await socket.__send_ping()

    async def _emit_server_stats(self):
        start_time = time.time()
        namespaces = list(self.sio.handlers.keys())
        namespaces.sort()
        while not self.stop_stats_event.is_set():
            await self.sio.sleep(self.server_stats_interval)
            await self.sio.emit('server_stats', {
                'serverId': self.server_id,
                'hostname': HOSTNAME,
                'pid': PID,
                'uptime': time.time() - start_time,
                'clientsCount': len(self.sio.eio.sockets),
                'pollingClientsCount': len(
                    [s for s in self.sio.eio.sockets.values()
                     if not s.upgraded]),
                'aggregatedEvents': self.event_buffer.get_and_clear(),
                'namespaces': [{
                    'name': nsp,
                    'socketsCount': len(self.sio.manager.rooms.get(
                        nsp, {None: []}).get(None, []))
                } for nsp in namespaces],
            }, namespace=self.admin_namespace)
            while self.admin_queue:
                event, args = self.admin_queue.pop(0)
                await self.sio.emit(event, args,
                                    namespace=self.admin_namespace)

    def serialize_socket(self, sid, namespace, eio_sid=None):
        if eio_sid is None:  # pragma: no cover
            eio_sid = self.sio.manager.eio_sid_from_sid(sid)
        socket = self.sio.eio._get_socket(eio_sid)
        environ = self.sio.environ.get(eio_sid, {})
        tm = self.sio.manager._timestamps[sid] if sid in \
            self.sio.manager._timestamps else 0
        return {
            'id': sid,
            'clientId': eio_sid,
            'transport': 'websocket' if socket.upgraded else 'polling',
            'nsp': namespace,
            'data': {},
            'handshake': {
                'address': environ.get('REMOTE_ADDR', ''),
                'headers': {k[5:].lower(): v for k, v in environ.items()
                            if k.startswith('HTTP_')},
                'query': {k: v[0] if len(v) == 1 else v for k, v in parse_qs(
                    environ.get('QUERY_STRING', '')).items()},
                'secure': environ.get('wsgi.url_scheme', '') == 'https',
                'url': environ.get('PATH_INFO', ''),
                'issued': tm * 1000,
                'time': datetime.fromtimestamp(tm, timezone.utc).isoformat()
                if tm else '',
            },
            'rooms': self.sio.manager.get_rooms(sid, namespace),
        }
