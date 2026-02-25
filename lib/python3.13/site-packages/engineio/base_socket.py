class BaseSocket:
    upgrade_protocols = ['websocket']

    def __init__(self, server, sid):
        self.server = server
        self.sid = sid
        self.queue = self.server.create_queue()
        self.last_ping = None
        self.connected = False
        self.upgrading = False
        self.upgraded = False
        self.closing = False
        self.closed = False
        self.session = {}
