import logging
import time
from urllib.parse import urlparse

try:
    import redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover
    redis = None
    RedisError = None

try:
    import valkey
    from valkey.exceptions import ValkeyError
except ImportError:  # pragma: no cover
    valkey = None
    ValkeyError = None

from .pubsub_manager import PubSubManager

logger = logging.getLogger('socketio')


def parse_redis_sentinel_url(url):
    """Parse a Redis Sentinel URL with the format:
    redis+sentinel://[:password]@host1:port1,host2:port2,.../db/service_name
    """
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {'redis+sentinel', 'valkey+sentinel'}:
        raise ValueError('Invalid Redis Sentinel URL')
    sentinels = []
    for host_port in parsed_url.netloc.split('@')[-1].split(','):
        host, port = host_port.rsplit(':', 1)
        sentinels.append((host, int(port)))
    kwargs = {}
    if parsed_url.username:
        kwargs['username'] = parsed_url.username
    if parsed_url.password:
        kwargs['password'] = parsed_url.password
    service_name = None
    if parsed_url.path:
        parts = parsed_url.path.split('/')
        if len(parts) >= 2 and parts[1] != '':
            kwargs['db'] = int(parts[1])
        if len(parts) >= 3 and parts[2] != '':
            service_name = parts[2]
    return sentinels, service_name, kwargs


class RedisManager(PubSubManager):
    """Redis based client manager.

    This class implements a Redis backend for event sharing across multiple
    processes. Only kept here as one more example of how to build a custom
    backend, since the kombu backend is perfectly adequate to support a Redis
    message queue.

    To use a Redis backend, initialize the :class:`Server` instance as
    follows::

        url = 'redis://hostname:port/0'
        server = socketio.Server(client_manager=socketio.RedisManager(url))

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
    name = 'redis'

    def __init__(self, url='redis://localhost:6379/0', channel='socketio',
                 write_only=False, logger=None, json=None, redis_options=None):
        super().__init__(channel=channel, write_only=write_only, logger=logger,
                         json=json)
        self.redis_url = url
        self.redis_options = redis_options or {}
        self.connected = False
        self.redis = None
        self.pubsub = None

    def initialize(self):  # pragma: no cover
        super().initialize()

        monkey_patched = True
        if self.server.async_mode == 'eventlet':
            from eventlet.patcher import is_monkey_patched
            monkey_patched = is_monkey_patched('socket')
        elif 'gevent' in self.server.async_mode:
            from gevent.monkey import is_module_patched
            monkey_patched = is_module_patched('socket')
        if not monkey_patched:
            raise RuntimeError(
                'Redis requires a monkey patched socket library to work '
                'with ' + self.server.async_mode)

    def _get_redis_module_and_error(self):
        parsed_url = urlparse(self.redis_url)
        scheme = parsed_url.scheme.split('+', 1)[0].lower()
        if scheme in ['redis', 'rediss']:
            if redis is None or RedisError is None:
                raise RuntimeError('Redis package is not installed '
                                   '(Run "pip install redis" '
                                   'in your virtualenv).')
            return redis, RedisError
        if scheme in ['valkey', 'valkeys']:
            if valkey is None or ValkeyError is None:
                raise RuntimeError('Valkey package is not installed '
                                   '(Run "pip install valkey" '
                                   'in your virtualenv).')
            return valkey, ValkeyError
        if scheme == 'unix':
            if redis is None or RedisError is None:
                if valkey is None or ValkeyError is None:
                    raise RuntimeError('Redis package is not installed '
                                       '(Run "pip install redis" '
                                       'or "pip install valkey" '
                                       'in your virtualenv).')
                else:
                    return valkey, ValkeyError
            else:
                return redis, RedisError
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

    def _publish(self, data):  # pragma: no cover
        _, error = self._get_redis_module_and_error()
        for retries_left in range(1, -1, -1):  # 2 attempts
            try:
                if not self.connected:
                    self._redis_connect()
                return self.redis.publish(self.channel, self.json.dumps(data))
            except error as exc:
                if retries_left > 0:
                    logger.error(
                        'Cannot publish to redis... retrying',
                        extra={"redis_exception": str(exc)}
                    )
                    self.connected = False
                else:
                    logger.error(
                        'Cannot publish to redis... giving up',
                        extra={"redis_exception": str(exc)}
                    )
                    break

    def _redis_listen_with_retries(self):  # pragma: no cover
        _, error = self._get_redis_module_and_error()
        retry_sleep = 1
        subscribed = False
        while True:
            try:
                if not subscribed:
                    self._redis_connect()
                    self.pubsub.subscribe(self.channel)
                    retry_sleep = 1
                yield from self.pubsub.listen()
            except error as exc:
                logger.error('Cannot receive from redis... '
                             f'retrying in {retry_sleep} secs',
                             extra={"redis_exception": str(exc)})
                subscribed = False
                time.sleep(retry_sleep)
                retry_sleep *= 2
                if retry_sleep > 60:
                    retry_sleep = 60

    def _listen(self):  # pragma: no cover
        channel = self.channel.encode('utf-8')
        for message in self._redis_listen_with_retries():
            if message['channel'] == channel and \
                    message['type'] == 'message' and 'data' in message:
                yield message['data']
        self.pubsub.unsubscribe(self.channel)
