import asyncio
from urllib.parse import urlparse

try:
    from redis import asyncio as aioredis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover
    try:
        import aioredis
        from aioredis.exceptions import RedisError
    except ImportError:
        aioredis = None
        RedisError = None

try:
    from valkey import asyncio as aiovalkey
    from valkey.exceptions import ValkeyError
except ImportError:  # pragma: no cover
    aiovalkey = None
    ValkeyError = None

from .async_pubsub_manager import AsyncPubSubManager
from .redis_manager import parse_redis_sentinel_url


class AsyncRedisManager(AsyncPubSubManager):
    """Redis based client manager for asyncio servers.

    This class implements a Redis backend for event sharing across multiple
    processes.

    To use a Redis backend, initialize the :class:`AsyncServer` instance as
    follows::

        url = 'redis://hostname:port/0'
        server = socketio.AsyncServer(
            client_manager=socketio.AsyncRedisManager(url))

    :param url: The connection URL for the Redis server. For a default Redis
                store running on the same host, use ``redis://``.  To use a
                TLS connection, use ``rediss://``. To use Redis Sentinel, use
                ``redis+sentinel://`` with a comma-separated list of hosts
                and the service name after the db in the URL path. Example:
                ``redis+sentinel://user:pw@host1:1234,host2:2345/0/myredis``.
    :param channel: The channel name on which the server sends and receives
                    notifications. Must be the same in all the servers.
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
    :param redis_options: additional keyword arguments to be passed to
                          ``Redis.from_url()`` or ``Sentinel()``.
    """
    name = 'aioredis'

    def __init__(self, url='redis://localhost:6379/0', channel='socketio',
                 write_only=False, logger=None, json=None, redis_options=None):
        if aioredis and \
                not hasattr(aioredis.Redis, 'from_url'):  # pragma: no cover
            raise RuntimeError('Version 2 of aioredis package is required.')
        super().__init__(channel=channel, write_only=write_only, logger=logger,
                         json=json)
        self.redis_url = url
        self.redis_options = redis_options or {}
        self.connected = False
        self.redis = None
        self.pubsub = None

    def _get_redis_module_and_error(self):
        parsed_url = urlparse(self.redis_url)
        scheme = parsed_url.scheme.split('+', 1)[0].lower()
        if scheme in ['redis', 'rediss']:
            if aioredis is None or RedisError is None:
                raise RuntimeError('Redis package is not installed '
                                   '(Run "pip install redis" '
                                   'in your virtualenv).')
            return aioredis, RedisError
        if scheme in ['valkey', 'valkeys']:
            if aiovalkey is None or ValkeyError is None:
                raise RuntimeError('Valkey package is not installed '
                                   '(Run "pip install valkey" '
                                   'in your virtualenv).')
            return aiovalkey, ValkeyError
        if scheme == 'unix':
            if aioredis is None or RedisError is None:
                if aiovalkey is None or ValkeyError is None:
                    raise RuntimeError('Redis package is not installed '
                                       '(Run "pip install redis" '
                                       'or "pip install valkey" '
                                       'in your virtualenv).')
                else:
                    return aiovalkey, ValkeyError
            else:
                return aioredis, RedisError
        error_msg = f'Unsupported Redis URL scheme: {scheme}'
        raise ValueError(error_msg)

    def _redis_connect(self):
        module, _ = self._get_redis_module_and_error()
        parsed_url = urlparse(self.redis_url)
        if parsed_url.scheme in {"redis+sentinel", "valkey+sentinel"}:
            sentinels, service_name, connection_kwargs = \
                parse_redis_sentinel_url(self.redis_url)
            kwargs = self.redis_options
            kwargs.update(connection_kwargs)
            sentinel = module.sentinel.Sentinel(sentinels, **kwargs)
            self.redis = sentinel.master_for(service_name or self.channel)
        else:
            self.redis = module.Redis.from_url(self.redis_url,
                                               **self.redis_options)
        self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        self.connected = True

    async def _publish(self, data):  # pragma: no cover
        _, error = self._get_redis_module_and_error()
        for retries_left in range(1, -1, -1):  # 2 attempts
            try:
                if not self.connected:
                    self._redis_connect()
                return await self.redis.publish(
                    self.channel, self.json.dumps(data))
            except error as exc:
                if retries_left > 0:
                    self._get_logger().error(
                        'Cannot publish to redis... '
                        'retrying',
                        extra={"redis_exception": str(exc)})
                    self.connected = False
                else:
                    self._get_logger().error(
                        'Cannot publish to redis... '
                        'giving up',
                        extra={"redis_exception": str(exc)})

                    break

    async def _redis_listen_with_retries(self):  # pragma: no cover
        _, error = self._get_redis_module_and_error()
        retry_sleep = 1
        subscribed = False
        while True:
            try:
                if not subscribed:
                    self._redis_connect()
                    await self.pubsub.subscribe(self.channel)
                    retry_sleep = 1
                async for message in self.pubsub.listen():
                    yield message
            except error as exc:
                self._get_logger().error('Cannot receive from redis... '
                                         'retrying in '
                                         f'{retry_sleep} secs',
                                         extra={"redis_exception": str(exc)})
                subscribed = False
                await asyncio.sleep(retry_sleep)
                retry_sleep *= 2
                if retry_sleep > 60:
                    retry_sleep = 60

    async def _listen(self):  # pragma: no cover
        channel = self.channel.encode('utf-8')
        async for message in self._redis_listen_with_retries():
            if message['channel'] == channel and \
                    message['type'] == 'message' and 'data' in message:
                yield message['data']
        await self.pubsub.unsubscribe(self.channel)
