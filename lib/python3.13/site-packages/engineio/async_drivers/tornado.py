import asyncio
import inspect
import sys
from urllib.parse import urlsplit
from .. import exceptions

import tornado.web
import tornado.websocket


def get_tornado_handler(engineio_server):
    class Handler(tornado.websocket.WebSocketHandler):  # pragma: no cover
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if isinstance(engineio_server.cors_allowed_origins, str):
                if engineio_server.cors_allowed_origins == '*':
                    self.allowed_origins = None
                else:
                    self.allowed_origins = [
                        engineio_server.cors_allowed_origins]
            else:
                self.allowed_origins = engineio_server.cors_allowed_origins
            self.receive_queue = asyncio.Queue()

        async def get(self, *args, **kwargs):
            if self.request.headers.get('Upgrade', '').lower() == 'websocket':
                ret = super().get(*args, **kwargs)
                if inspect.iscoroutine(ret):
                    await ret
            else:
                await engineio_server.handle_request(self)

        async def open(self, *args, **kwargs):
            # this is the handler for the websocket request
            asyncio.ensure_future(engineio_server.handle_request(self))

        async def post(self, *args, **kwargs):
            await engineio_server.handle_request(self)

        async def options(self, *args, **kwargs):
            await engineio_server.handle_request(self)

        async def on_message(self, message):
            await self.receive_queue.put(message)

        async def get_next_message(self):
            return await self.receive_queue.get()

        def on_close(self):
            self.receive_queue.put_nowait(None)

        def check_origin(self, origin):
            if self.allowed_origins is None or origin in self.allowed_origins:
                return True
            return super().check_origin(origin)

        def get_compression_options(self):
            # enable compression
            return {}

    return Handler


def translate_request(handler):
    """This function takes the arguments passed to the request handler and
    uses them to generate a WSGI compatible environ dictionary.
    """
    class AwaitablePayload:
        def __init__(self, payload):
            self.payload = payload or b''

        async def read(self, length=None):
            if length is None:
                r = self.payload
                self.payload = b''
            else:
                r = self.payload[:length]
                self.payload = self.payload[length:]
            return r

    payload = handler.request.body

    uri_parts = urlsplit(handler.request.path)
    full_uri = handler.request.path
    if handler.request.query:  # pragma: no cover
        full_uri += '?' + handler.request.query
    environ = {
        'wsgi.input': AwaitablePayload(payload),
        'wsgi.errors': sys.stderr,
        'wsgi.version': (1, 0),
        'wsgi.async': True,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
        'SERVER_SOFTWARE': 'aiohttp',
        'REQUEST_METHOD': handler.request.method,
        'QUERY_STRING': handler.request.query or '',
        'RAW_URI': full_uri,
        'SERVER_PROTOCOL': 'HTTP/%s' % handler.request.version,
        'REMOTE_ADDR': '127.0.0.1',
        'REMOTE_PORT': '0',
        'SERVER_NAME': 'aiohttp',
        'SERVER_PORT': '0',
        'tornado.handler': handler
    }

    for hdr_name, hdr_value in handler.request.headers.items():
        hdr_name = hdr_name.upper()
        if hdr_name == 'CONTENT-TYPE':
            environ['CONTENT_TYPE'] = hdr_value
            continue
        elif hdr_name == 'CONTENT-LENGTH':
            environ['CONTENT_LENGTH'] = hdr_value
            continue

        key = 'HTTP_%s' % hdr_name.replace('-', '_')
        environ[key] = hdr_value

    environ['wsgi.url_scheme'] = environ.get('HTTP_X_FORWARDED_PROTO', 'http')

    path_info = uri_parts.path

    environ['PATH_INFO'] = path_info
    environ['SCRIPT_NAME'] = ''

    return environ


def make_response(status, headers, payload, environ):
    """This function generates an appropriate response object for this async
    mode.
    """
    tornado_handler = environ['tornado.handler']
    try:
        tornado_handler.set_status(int(status.split()[0]))
    except RuntimeError:  # pragma: no cover
        # for websocket connections Tornado does not accept a response, since
        # it already emitted the 101 status code
        return
    for header, value in headers:
        tornado_handler.set_header(header, value)
    tornado_handler.write(payload)
    tornado_handler.finish()


class WebSocket:  # pragma: no cover
    """
    This wrapper class provides a tornado WebSocket interface that is
    somewhat compatible with eventlet's implementation.
    """
    def __init__(self, handler, server):
        self.handler = handler
        self.tornado_handler = None

    async def __call__(self, environ):
        self.tornado_handler = environ['tornado.handler']
        self.environ = environ
        await self.handler(self)

    async def close(self):
        self.tornado_handler.close()

    async def send(self, message):
        try:
            self.tornado_handler.write_message(
                message, binary=isinstance(message, bytes))
        except tornado.websocket.WebSocketClosedError:
            raise exceptions.EngineIOError()

    async def wait(self):
        msg = await self.tornado_handler.get_next_message()
        if not isinstance(msg, bytes) and \
                not isinstance(msg, str):
            raise OSError()
        return msg


_async = {
    'asyncio': True,
    'translate_request': translate_request,
    'make_response': make_response,
    'websocket': WebSocket,
}
