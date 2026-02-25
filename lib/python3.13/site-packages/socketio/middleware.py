import engineio


class WSGIApp(engineio.WSGIApp):
    """WSGI middleware for Socket.IO.

    This middleware dispatches traffic to a Socket.IO application. It can also
    serve a list of static files to the client, or forward unrelated HTTP
    traffic to another WSGI application.

    :param socketio_app: The Socket.IO server. Must be an instance of the
                         ``socketio.Server`` class.
    :param wsgi_app: The WSGI app that receives all other traffic.
    :param static_files: A dictionary with static file mapping rules. See the
                         documentation for details on this argument.
    :param socketio_path: The endpoint where the Socket.IO application should
                          be installed. The default value is appropriate for
                          most cases.

    Example usage::

        import socketio
        import eventlet
        from . import wsgi_app

        sio = socketio.Server()
        app = socketio.WSGIApp(sio, wsgi_app)
        eventlet.wsgi.server(eventlet.listen(('', 8000)), app)
    """
    def __init__(self, socketio_app, wsgi_app=None, static_files=None,
                 socketio_path='socket.io'):
        super().__init__(socketio_app, wsgi_app, static_files=static_files,
                         engineio_path=socketio_path)


class Middleware(WSGIApp):
    """This class has been renamed to WSGIApp and is now deprecated."""
    def __init__(self, socketio_app, wsgi_app=None,
                 socketio_path='socket.io'):
        super().__init__(socketio_app, wsgi_app, socketio_path=socketio_path)
