from .errors import ConnectionClosed  # pragma: no cover


class WebSocketASGI:  # pragma: no cover
    def __init__(self, scope, receive, send, subprotocols=None):
        self._scope = scope
        self._receive = receive
        self._send = send
        self.subprotocols = subprotocols or []
        self.subprotocol = None
        self.connected = False

    @classmethod
    async def accept(cls, scope, receive, send, subprotocols=None):
        ws = WebSocketASGI(scope, receive, send, subprotocols=subprotocols)
        await ws._accept()
        return ws

    async def _accept(self):
        connect = await self._receive()
        if connect['type'] != 'websocket.connect':
            raise ValueError('Expected websocket.connect')
        for subprotocol in self._scope['subprotocols']:
            if subprotocol in self.subprotocols:
                self.subprotocol = subprotocol
                break
        await self._send({'type': 'websocket.accept',
                         'subprotocol': self.subprotocol})

    async def receive(self):
        message = await self._receive()
        if message['type'] == 'websocket.disconnect':
            raise ConnectionClosed()
        elif message['type'] != 'websocket.receive':
            raise OSError(32, 'Websocket message type not supported')
        return message.get('text', message.get('bytes'))

    async def send(self, data):
        if isinstance(data, str):
            await self._send({'type': 'websocket.send', 'text': data})
        else:
            await self._send({'type': 'websocket.send', 'bytes': data})

    async def close(self):
        if not self.connected:
            self.conncted = False
            try:
                await self._send({'type': 'websocket.close'})
            except Exception:
                pass
