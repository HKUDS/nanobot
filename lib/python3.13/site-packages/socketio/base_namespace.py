class BaseNamespace:
    def __init__(self, namespace=None):
        self.namespace = namespace or '/'

    def is_asyncio_based(self):
        return False


class BaseServerNamespace(BaseNamespace):
    def __init__(self, namespace=None):
        super().__init__(namespace=namespace)
        self.server = None

    def _set_server(self, server):
        self.server = server

    def rooms(self, sid, namespace=None):
        """Return the rooms a client is in.

        The only difference with the :func:`socketio.Server.rooms` method is
        that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.server.rooms(sid, namespace=namespace or self.namespace)


class BaseClientNamespace(BaseNamespace):
    def __init__(self, namespace=None):
        super().__init__(namespace=namespace)
        self.client = None

    def _set_client(self, client):
        self.client = client
