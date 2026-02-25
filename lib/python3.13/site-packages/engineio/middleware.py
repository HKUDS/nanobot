import os
from engineio.static_files import get_static_file


class WSGIApp:
    """WSGI application middleware for Engine.IO.

    This middleware dispatches traffic to an Engine.IO application. It can
    also serve a list of static files to the client, or forward unrelated
    HTTP traffic to another WSGI application.

    :param engineio_app: The Engine.IO server. Must be an instance of the
                         ``engineio.Server`` class.
    :param wsgi_app: The WSGI app that receives all other traffic.
    :param static_files: A dictionary with static file mapping rules. See the
                         documentation for details on this argument.
    :param engineio_path: The endpoint where the Engine.IO application should
                          be installed. The default value is appropriate for
                          most cases.

    Example usage::

        import engineio
        import eventlet

        eio = engineio.Server()
        app = engineio.WSGIApp(eio, static_files={
            '/': {'content_type': 'text/html', 'filename': 'index.html'},
            '/index.html': {'content_type': 'text/html',
                            'filename': 'index.html'},
        })
        eventlet.wsgi.server(eventlet.listen(('', 8000)), app)
    """
    def __init__(self, engineio_app, wsgi_app=None, static_files=None,
                 engineio_path='engine.io'):
        self.engineio_app = engineio_app
        self.wsgi_app = wsgi_app
        self.engineio_path = engineio_path
        if not self.engineio_path.startswith('/'):
            self.engineio_path = '/' + self.engineio_path
        if not self.engineio_path.endswith('/'):
            self.engineio_path += '/'
        self.static_files = static_files or {}

    def __call__(self, environ, start_response):
        if 'gunicorn.socket' in environ:
            # gunicorn saves the socket under environ['gunicorn.socket'], while
            # eventlet saves it under environ['eventlet.input']. Eventlet also
            # stores the socket inside a wrapper class, while gunicon writes it
            # directly into the environment. To give eventlet's WebSocket
            # module access to this socket when running under gunicorn, here we
            # copy the socket to the eventlet format.
            class Input:
                def __init__(self, socket):
                    self.socket = socket

                def get_socket(self):
                    return self.socket

            environ['eventlet.input'] = Input(environ['gunicorn.socket'])
        path = environ['PATH_INFO']
        if path is not None and path.startswith(self.engineio_path):
            return self.engineio_app.handle_request(environ, start_response)
        else:
            static_file = get_static_file(path, self.static_files) \
                if self.static_files else None
            if static_file and os.path.exists(static_file['filename']):
                start_response(
                    '200 OK',
                    [('Content-Type', static_file['content_type'])])
                with open(static_file['filename'], 'rb') as f:
                    return [f.read()]
            elif self.wsgi_app is not None:
                return self.wsgi_app(environ, start_response)
        return self.not_found(start_response)

    def not_found(self, start_response):
        start_response("404 Not Found", [('Content-Type', 'text/plain')])
        return [b'Not Found']


class Middleware(WSGIApp):
    """This class has been renamed to ``WSGIApp`` and is now deprecated."""
    def __init__(self, engineio_app, wsgi_app=None,
                 engineio_path='engine.io'):
        super().__init__(engineio_app, wsgi_app, engineio_path=engineio_path)
