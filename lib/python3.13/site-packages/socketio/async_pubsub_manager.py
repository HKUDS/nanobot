import asyncio
import base64
from functools import partial
import uuid

from .async_manager import AsyncManager
from .packet import Packet


class AsyncPubSubManager(AsyncManager):
    """Manage a client list attached to a pub/sub backend under asyncio.

    This is a base class that enables multiple servers to share the list of
    clients, with the servers communicating events through a pub/sub backend.
    The use of a pub/sub backend also allows any client connected to the
    backend to emit events addressed to Socket.IO clients.

    The actual backends must be implemented by subclasses, this class only
    provides a pub/sub generic framework for asyncio applications.

    :param channel: The channel name on which the server sends and receives
                    notifications.
    :param write_only: If set to ``True``, only initialize to emit events. The
                       default of ``False`` initializes the class for emitting
                       and receiving. A write-only instance can be used
                       independently of the server to emit to clients from an
                       external process.
    :param logger: a custom logger to log it. If not given, the server logger
                   is used.
    :param json: An alternative JSON module to use for encoding and decoding
                 packets. Custom json modules must have ``dumps`` and ``loads``
                 functions that are compatible with the standard library
                 versions. This setting is only used when ``write_only`` is set
                 to ``True``. Otherwise the JSON module configured in the
                 server is used.
    """
    name = 'asyncpubsub'

    def __init__(self, channel='socketio', write_only=False, logger=None,
                 json=None):
        super().__init__()
        self.channel = channel
        self.write_only = write_only
        self.host_id = uuid.uuid4().hex
        self.logger = logger
        if json is not None:
            self.json = json

    def initialize(self):
        super().initialize()
        if not self.write_only:
            self.thread = self.server.start_background_task(self._thread)
        self._get_logger().info(self.name + ' backend initialized.')

    async def emit(self, event, data, namespace=None, room=None, skip_sid=None,
                   callback=None, to=None, **kwargs):
        """Emit a message to a single client, a room, or all the clients
        connected to the namespace.

        This method takes care or propagating the message to all the servers
        that are connected through the message queue.

        The parameters are the same as in :meth:`.Server.emit`.

        Note: this method is a coroutine.
        """
        room = to or room
        if kwargs.get('ignore_queue'):
            return await super().emit(
                event, data, namespace=namespace, room=room, skip_sid=skip_sid,
                callback=callback)
        namespace = namespace or '/'
        if callback is not None:
            if self.server is None:
                raise RuntimeError('Callbacks can only be issued from the '
                                   'context of a server.')
            if room is None:
                raise ValueError('Cannot use callback without a room set.')
            id = self._generate_ack_id(room, callback)
            callback = (room, namespace, id)
        else:
            callback = None
        if isinstance(data, tuple):
            data = list(data)
        else:
            data = [data]
        binary = Packet.data_is_binary(data)
        if binary:
            data, attachments = Packet.deconstruct_binary(data)
            data = [data, *[base64.b64encode(a).decode() for a in attachments]]
        message = {'method': 'emit', 'event': event, 'data': data,
                   'binary': binary, 'namespace': namespace, 'room': room,
                   'skip_sid': skip_sid, 'callback': callback,
                   'host_id': self.host_id}
        await self._handle_emit(message)  # handle in this host
        await self._publish(message)  # notify other hosts

    async def can_disconnect(self, sid, namespace):
        if self.is_connected(sid, namespace):
            # client is in this server, so we can disconnect directly
            return await super().can_disconnect(sid, namespace)
        else:
            # client is in another server, so we post request to the queue
            await self._publish({'method': 'disconnect', 'sid': sid,
                                 'namespace': namespace or '/',
                                 'host_id': self.host_id})

    async def disconnect(self, sid, namespace, **kwargs):
        if kwargs.get('ignore_queue'):
            return await super().disconnect(
                sid, namespace=namespace)
        message = {'method': 'disconnect', 'sid': sid,
                   'namespace': namespace or '/', 'host_id': self.host_id}
        await self._handle_disconnect(message)  # handle in this host
        await self._publish(message)  # notify other hosts

    async def enter_room(self, sid, namespace, room, eio_sid=None):
        if self.is_connected(sid, namespace):
            # client is in this server, so we can disconnect directly
            return await super().enter_room(sid, namespace, room,
                                            eio_sid=eio_sid)
        else:
            message = {'method': 'enter_room', 'sid': sid, 'room': room,
                       'namespace': namespace or '/', 'host_id': self.host_id}
            await self._publish(message)  # notify other hosts

    async def leave_room(self, sid, namespace, room):
        if self.is_connected(sid, namespace):
            # client is in this server, so we can disconnect directly
            return await super().leave_room(sid, namespace, room)
        else:
            message = {'method': 'leave_room', 'sid': sid, 'room': room,
                       'namespace': namespace or '/', 'host_id': self.host_id}
            await self._publish(message)  # notify other hosts

    async def close_room(self, room, namespace=None):
        message = {'method': 'close_room', 'room': room,
                   'namespace': namespace or '/', 'host_id': self.host_id}
        await self._handle_close_room(message)  # handle in this host
        await self._publish(message)  # notify other hosts

    async def _publish(self, data):
        """Publish a message on the Socket.IO channel.

        This method needs to be implemented by the different subclasses that
        support pub/sub backends.
        """
        raise NotImplementedError('This method must be implemented in a '
                                  'subclass.')  # pragma: no cover

    async def _listen(self):
        """Return the next message published on the Socket.IO channel,
        blocking until a message is available.

        This method needs to be implemented by the different subclasses that
        support pub/sub backends.
        """
        raise NotImplementedError('This method must be implemented in a '
                                  'subclass.')  # pragma: no cover

    async def _handle_emit(self, message):
        # Events with callbacks are very tricky to handle across hosts
        # Here in the receiving end we set up a local callback that preserves
        # the callback host and id from the sender
        remote_callback = message.get('callback')
        remote_host_id = message.get('host_id')
        if remote_callback is not None and len(remote_callback) == 3:
            callback = partial(self._return_callback, remote_host_id,
                               *remote_callback)
        else:
            callback = None
        data = message['data']
        if message.get('binary'):
            attachments = [base64.b64decode(a) for a in data[1:]]
            data = Packet.reconstruct_binary(data[0], attachments)
        if isinstance(data, list):
            if len(data) == 1:
                data = data[0]
            else:
                data = tuple(data)
        await super().emit(message['event'], data,
                           namespace=message.get('namespace'),
                           room=message.get('room'),
                           skip_sid=message.get('skip_sid'),
                           callback=callback)

    async def _handle_callback(self, message):
        if self.host_id == message.get('host_id'):
            try:
                sid = message['sid']
                id = message['id']
                args = message['args']
            except KeyError:
                return
            await self.trigger_callback(sid, id, args)

    async def _return_callback(self, host_id, sid, namespace, callback_id,
                               *args):
        # When an event callback is received, the callback is returned back
        # the sender, which is identified by the host_id
        if host_id == self.host_id:
            await self.trigger_callback(sid, callback_id, args)
        else:
            await self._publish({'method': 'callback', 'host_id': host_id,
                                 'sid': sid, 'namespace': namespace,
                                 'id': callback_id, 'args': args})

    async def _handle_disconnect(self, message):
        await self.server.disconnect(sid=message.get('sid'),
                                     namespace=message.get('namespace'),
                                     ignore_queue=True)

    async def _handle_enter_room(self, message):
        sid = message.get('sid')
        namespace = message.get('namespace')
        if self.is_connected(sid, namespace):
            await super().enter_room(sid, namespace, message.get('room'))

    async def _handle_leave_room(self, message):
        sid = message.get('sid')
        namespace = message.get('namespace')
        if self.is_connected(sid, namespace):
            await super().leave_room(sid, namespace, message.get('room'))

    async def _handle_close_room(self, message):
        await super().close_room(room=message.get('room'),
                                 namespace=message.get('namespace'))

    async def _thread(self):
        while True:
            try:
                async for message in self._listen():  # pragma: no branch
                    data = None
                    if isinstance(message, dict):
                        data = message
                    else:
                        try:
                            data = self.json.loads(message)
                        except:
                            pass
                    if data and 'method' in data:
                        self._get_logger().debug('pubsub message: {}'.format(
                            data['method']))
                        try:
                            if data['method'] == 'callback':
                                await self._handle_callback(data)
                            elif data.get('host_id') != self.host_id:
                                if data['method'] == 'emit':
                                    await self._handle_emit(data)
                                elif data['method'] == 'disconnect':
                                    await self._handle_disconnect(data)
                                elif data['method'] == 'enter_room':
                                    await self._handle_enter_room(data)
                                elif data['method'] == 'leave_room':
                                    await self._handle_leave_room(data)
                                elif data['method'] == 'close_room':
                                    await self._handle_close_room(data)
                        except asyncio.CancelledError:
                            raise  # let the outer try/except handle it
                        except Exception:
                            self.server.logger.exception(
                                'Handler error in pubsub listening thread')
                self.server.logger.error('pubsub listen() exited unexpectedly')
                break  # loop should never exit except in unit tests!
            except asyncio.CancelledError:  # pragma: no cover
                break
            except Exception:  # pragma: no cover
                self.server.logger.exception('Unexpected Error in pubsub '
                                             'listening thread')
