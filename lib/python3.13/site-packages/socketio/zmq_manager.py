import re

from .pubsub_manager import PubSubManager


class ZmqManager(PubSubManager):  # pragma: no cover
    """zmq based client manager.

    NOTE: this zmq implementation should be considered experimental at this
    time. At this time, eventlet is required to use zmq.

    This class implements a zmq backend for event sharing across multiple
    processes. To use a zmq backend, initialize the :class:`Server` instance as
    follows::

        url = 'zmq+tcp://hostname:port1+port2'
        server = socketio.Server(client_manager=socketio.ZmqManager(url))

    :param url: The connection URL for the zmq message broker,
                which will need to be provided and running.
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

    A zmq message broker must be running for the zmq_manager to work.
    you can write your own or adapt one from the following simple broker
    below::

        import zmq

        receiver = zmq.Context().socket(zmq.PULL)
        receiver.bind("tcp://*:5555")

        publisher = zmq.Context().socket(zmq.PUB)
        publisher.bind("tcp://*:5556")

        while True:
            publisher.send(receiver.recv())
    """
    name = 'zmq'

    def __init__(self, url='zmq+tcp://localhost:5555+5556', channel='socketio',
                 write_only=False, logger=None, json=None):
        try:
            from eventlet.green import zmq
        except ImportError:
            raise RuntimeError('zmq package is not installed '
                               '(Run "pip install pyzmq" in your '
                               'virtualenv).')

        r = re.compile(r':\d+\+\d+$')
        if not (url.startswith('zmq+tcp://') and r.search(url)):
            raise RuntimeError('unexpected connection string: ' + url)

        super().__init__(channel=channel, write_only=write_only, logger=logger,
                         json=json)
        url = url.replace('zmq+', '')
        (sink_url, sub_port) = url.split('+')
        sink_port = sink_url.split(':')[-1]
        sub_url = sink_url.replace(sink_port, sub_port)

        sink = zmq.Context().socket(zmq.PUSH)
        sink.connect(sink_url)

        sub = zmq.Context().socket(zmq.SUB)
        sub.setsockopt_string(zmq.SUBSCRIBE, '')
        sub.connect(sub_url)

        self.sink = sink
        self.sub = sub
        self.channel = channel

    def _publish(self, data):
        packed_data = self.json.dumps(
            {
                'type': 'message',
                'channel': self.channel,
                'data': data
            }
        ).encode()
        return self.sink.send(packed_data)

    def zmq_listen(self):
        while True:
            response = self.sub.recv()
            if response is not None:
                yield response

    def _listen(self):
        for message in self.zmq_listen():
            if isinstance(message, bytes):
                try:
                    message = self.json.loads(message)
                except Exception:
                    pass
            if isinstance(message, dict) and \
                    message['type'] == 'message' and \
                    message['channel'] == self.channel and \
                    'data' in message:
                yield message['data']
        return
