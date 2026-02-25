import engineio


class ASGIApp(engineio.ASGIApp):  # pragma: no cover
    """ASGI application middleware for Socket.IO.

    This middleware dispatches traffic to an Socket.IO application. It can
    also serve a list of static files to the client, or forward unrelated
    HTTP traffic to another ASGI application.

    :param socketio_server: The Socket.IO server. Must be an instance of the
                            ``socketio.AsyncServer`` class.
    :param static_files: A dictionary with static file mapping rules. See the
                         documentation for details on this argument.
    :param other_asgi_app: A separate ASGI app that receives all other traffic.
    :param socketio_path: The endpoint where the Socket.IO application should
                          be installed. The default value is appropriate for
                          most cases. With a value of ``None``, all incoming
                          traffic is directed to the Socket.IO server, with the
                          assumption that routing, if necessary, is handled by
                          a different layer. When this option is set to
                          ``None``, ``static_files`` and ``other_asgi_app`` are
                          ignored.
    :param on_startup: function to be called on application startup; can be
                       coroutine
    :param on_shutdown: function to be called on application shutdown; can be
                        coroutine

    Example usage::

        import socketio
        import uvicorn

        sio = socketio.AsyncServer()
        app = socketio.ASGIApp(sio, static_files={
            '/': 'index.html',
            '/static': './public',
        })
        uvicorn.run(app, host='127.0.0.1', port=5000)
    """
    def __init__(self, socketio_server, other_asgi_app=None,
                 static_files=None, socketio_path='socket.io',
                 on_startup=None, on_shutdown=None):
        super().__init__(socketio_server, other_asgi_app,
                         static_files=static_files,
                         engineio_path=socketio_path, on_startup=on_startup,
                         on_shutdown=on_shutdown)
