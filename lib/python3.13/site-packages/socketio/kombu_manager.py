import time
import uuid

try:
    import kombu
except ImportError:
    kombu = None

from .pubsub_manager import PubSubManager


class KombuManager(PubSubManager):  # pragma: no cover
    """Client manager that uses kombu for inter-process messaging.

    This class implements a client manager backend for event sharing across
    multiple processes, using RabbitMQ, Redis or any other messaging mechanism
    supported by `kombu <http://kombu.readthedocs.org/en/latest/>`_.

    To use a kombu backend, initialize the :class:`Server` instance as
    follows::

        url = 'amqp://user:password@hostname:port//'
        server = socketio.Server(client_manager=socketio.KombuManager(url))

    :param url: The connection URL for the backend messaging queue. Example
                connection URLs are ``'amqp://guest:guest@localhost:5672//'``
                and ``'redis://localhost:6379/'`` for RabbitMQ and Redis
                respectively. Consult the `kombu documentation
                <http://kombu.readthedocs.org/en/latest/userguide\
                /connections.html#urls>`_ for more on how to construct
                connection URLs.
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
    :param connection_options: additional keyword arguments to be passed to
                               ``kombu.Connection()``.
    :param exchange_options: additional keyword arguments to be passed to
                             ``kombu.Exchange()``.
    :param queue_options: additional keyword arguments to be passed to
                          ``kombu.Queue()``.
    :param producer_options: additional keyword arguments to be passed to
                             ``kombu.Producer()``.
    """
    name = 'kombu'

    def __init__(self, url='amqp://guest:guest@localhost:5672//',
                 channel='socketio', write_only=False, logger=None, json=None,
                 connection_options=None, exchange_options=None,
                 queue_options=None, producer_options=None):
        if kombu is None:
            raise RuntimeError('Kombu package is not installed '
                               '(Run "pip install kombu" in your '
                               'virtualenv).')
        super().__init__(channel=channel, write_only=write_only, logger=logger,
                         json=json)
        self.url = url
        self.connection_options = connection_options or {}
        self.exchange_options = exchange_options or {}
        self.queue_options = queue_options or {}
        self.producer_options = producer_options or {}
        self.publisher_connection = self._connection()

    def initialize(self):
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
                'Kombu requires a monkey patched socket library to work '
                'with ' + self.server.async_mode)

    def _connection(self):
        return kombu.Connection(self.url, **self.connection_options)

    def _exchange(self):
        options = {'type': 'fanout', 'durable': False}
        options.update(self.exchange_options)
        return kombu.Exchange(self.channel, **options)

    def _queue(self):
        queue_name = 'python-socketio.' + str(uuid.uuid4())
        options = {'durable': False, 'queue_arguments': {'x-expires': 300000}}
        options.update(self.queue_options)
        return kombu.Queue(queue_name, self._exchange(), **options)

    def _producer_publish(self, connection):
        producer = connection.Producer(exchange=self._exchange(),
                                       **self.producer_options)
        return connection.ensure(producer, producer.publish)

    def _publish(self, data):
        retry = True
        while True:
            try:
                producer_publish = self._producer_publish(
                    self.publisher_connection)
                producer_publish(self.json.dumps(data))
                break
            except (OSError, kombu.exceptions.KombuError):
                if retry:
                    self._get_logger().error('Cannot publish to rabbitmq... '
                                             'retrying')
                    retry = False
                else:
                    self._get_logger().error(
                        'Cannot publish to rabbitmq... giving up')
                    break

    def _listen(self):
        retry_sleep = 1
        while True:
            try:
                reader_queue = self._queue()
                with self._connection() as connection:
                    with connection.SimpleQueue(reader_queue) as queue:
                        while True:
                            message = queue.get(block=True)
                            message.ack()
                            yield message.payload
                            retry_sleep = 1
            except (OSError, kombu.exceptions.KombuError):
                self._get_logger().error(
                    'Cannot receive from rabbitmq... '
                    'retrying in {} secs'.format(retry_sleep))
                time.sleep(retry_sleep)
                retry_sleep = min(retry_sleep * 2, 60)
