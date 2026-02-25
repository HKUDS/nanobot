import logging

try:
    import kafka
except ImportError:
    kafka = None

from .pubsub_manager import PubSubManager

logger = logging.getLogger('socketio')


class KafkaManager(PubSubManager):  # pragma: no cover
    """Kafka based client manager.

    This class implements a Kafka backend for event sharing across multiple
    processes.

    To use a Kafka backend, initialize the :class:`Server` instance as
    follows::

        url = 'kafka://hostname:port'
        server = socketio.Server(client_manager=socketio.KafkaManager(url))

    :param url: The connection URL for the Kafka server. For a default Kafka
                store running on the same host, use ``kafka://``. For a highly
                available deployment of Kafka, pass a list with all the
                connection URLs available in your cluster.
    :param channel: The channel name (topic) on which the server sends and
                    receives notifications. Must be the same in all the
                    servers.
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
    name = 'kafka'

    def __init__(self, url='kafka://localhost:9092', channel='socketio',
                 write_only=False, logger=None, json=None):
        if kafka is None:
            raise RuntimeError('kafka-python package is not installed '
                               '(Run "pip install kafka-python" in your '
                               'virtualenv).')

        super().__init__(channel=channel, write_only=write_only, logger=logger,
                         json=json)

        urls = [url] if isinstance(url, str) else url
        self.kafka_urls = [url[8:] if url != 'kafka://' else 'localhost:9092'
                           for url in urls]
        self.producer = kafka.KafkaProducer(bootstrap_servers=self.kafka_urls)
        self.consumer = kafka.KafkaConsumer(self.channel,
                                            bootstrap_servers=self.kafka_urls)

    def _publish(self, data):
        self.producer.send(self.channel, value=self.json.dumps(data))
        self.producer.flush()

    def _kafka_listen(self):
        yield from self.consumer

    def _listen(self):
        for message in self._kafka_listen():
            if message.topic == self.channel:
                yield message.value
