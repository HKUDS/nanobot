import itertools
import logging
import json

from bidict import bidict, ValueDuplicationError

default_logger = logging.getLogger('socketio')


class BaseManager:
    def __init__(self):
        self.logger = None
        self.server = None
        self.rooms = {}  # self.rooms[namespace][room][sio_sid] = eio_sid
        self.eio_to_sid = {}
        self.callbacks = {}
        self.pending_disconnect = {}
        self.json = json

    def set_server(self, server):
        self.server = server
        self.json = self.server.packet_class.json  # use the global JSON module

    def initialize(self):
        """Invoked before the first request is received. Subclasses can add
        their initialization code here.
        """
        pass

    def get_namespaces(self):
        """Return an iterable with the active namespace names."""
        return self.rooms.keys()

    def get_participants(self, namespace, room):
        """Return an iterable with the active participants in a room.

        Note that in a multi-server scenario this method only returns the
        participants connect to the server in which the method is called. There
        is currently no functionality to assemble a complete list of users
        across multiple servers.
        """
        ns = self.rooms.get(namespace, {})
        if hasattr(room, '__len__') and not isinstance(room, str):
            participants = ns[room[0]]._fwdm.copy() if room[0] in ns else {}
            for r in room[1:]:
                participants.update(ns[r]._fwdm if r in ns else {})
        else:
            participants = ns[room]._fwdm.copy() if room in ns else {}
        yield from participants.items()

    def connect(self, eio_sid, namespace):
        """Register a client connection to a namespace."""
        sid = self.server.eio.generate_id()
        try:
            self.basic_enter_room(sid, namespace, None, eio_sid=eio_sid)
        except ValueDuplicationError:
            # already connected
            return None
        self.basic_enter_room(sid, namespace, sid, eio_sid=eio_sid)
        return sid

    def is_connected(self, sid, namespace):
        if namespace in self.pending_disconnect and \
                sid in self.pending_disconnect[namespace]:
            # the client is in the process of being disconnected
            return False
        try:
            return self.rooms[namespace][None][sid] is not None
        except KeyError:
            pass
        return False

    def sid_from_eio_sid(self, eio_sid, namespace):
        try:
            return self.rooms[namespace][None]._invm[eio_sid]
        except KeyError:
            pass

    def eio_sid_from_sid(self, sid, namespace):
        if namespace in self.rooms:
            return self.rooms[namespace][None].get(sid)

    def pre_disconnect(self, sid, namespace):
        """Put the client in the to-be-disconnected list.

        This allows the client data structures to be present while the
        disconnect handler is invoked, but still recognize the fact that the
        client is soon going away.
        """
        if namespace not in self.pending_disconnect:
            self.pending_disconnect[namespace] = []
        self.pending_disconnect[namespace].append(sid)
        return self.rooms[namespace][None].get(sid)

    def basic_disconnect(self, sid, namespace, **kwargs):
        if namespace not in self.rooms:
            return
        rooms = []
        for room_name, room in self.rooms[namespace].copy().items():
            if sid in room:
                rooms.append(room_name)
        for room in rooms:
            self.basic_leave_room(sid, namespace, room)
        if sid in self.callbacks:
            del self.callbacks[sid]
        if namespace in self.pending_disconnect and \
                sid in self.pending_disconnect[namespace]:
            self.pending_disconnect[namespace].remove(sid)
            if len(self.pending_disconnect[namespace]) == 0:
                del self.pending_disconnect[namespace]

    def basic_enter_room(self, sid, namespace, room, eio_sid=None):
        if eio_sid is None and namespace not in self.rooms:
            raise ValueError('sid is not connected to requested namespace')
        if namespace not in self.rooms:
            self.rooms[namespace] = {}
        if room not in self.rooms[namespace]:
            self.rooms[namespace][room] = bidict()
        if eio_sid is None:
            eio_sid = self.rooms[namespace][None][sid]
        self.rooms[namespace][room][sid] = eio_sid

    def basic_leave_room(self, sid, namespace, room):
        try:
            del self.rooms[namespace][room][sid]
            if len(self.rooms[namespace][room]) == 0:
                del self.rooms[namespace][room]
                if len(self.rooms[namespace]) == 0:
                    del self.rooms[namespace]
        except KeyError:
            pass

    def basic_close_room(self, room, namespace):
        try:
            for sid, _ in self.get_participants(namespace, room):
                self.basic_leave_room(sid, namespace, room)
        except KeyError:  # pragma: no cover
            pass

    def get_rooms(self, sid, namespace):
        """Return the rooms a client is in."""
        r = []
        try:
            for room_name, room in self.rooms[namespace].items():
                if room_name is not None and sid in room:
                    r.append(room_name)
        except KeyError:
            pass
        return r

    def _generate_ack_id(self, sid, callback):
        """Generate a unique identifier for an ACK packet."""
        if sid not in self.callbacks:
            self.callbacks[sid] = {0: itertools.count(1)}
        id = next(self.callbacks[sid][0])
        self.callbacks[sid][id] = callback
        return id

    def _get_logger(self):
        """Get the appropriate logger

        Prevents uninitialized servers in write-only mode from failing.
        """

        if self.logger:
            return self.logger
        elif self.server:
            return self.server.logger
        else:
            return default_logger
