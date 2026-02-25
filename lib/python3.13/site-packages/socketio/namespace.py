from . import base_namespace


class Namespace(base_namespace.BaseServerNamespace):
    """Base class for server-side class-based namespaces.

    A class-based namespace is a class that contains all the event handlers
    for a Socket.IO namespace. The event handlers are methods of the class
    with the prefix ``on_``, such as ``on_connect``, ``on_disconnect``,
    ``on_message``, ``on_json``, and so on.

    :param namespace: The Socket.IO namespace to be used with all the event
                      handlers defined in this class. If this argument is
                      omitted, the default namespace is used.
    """
    def trigger_event(self, event, *args):
        """Dispatch an event to the proper handler method.

        In the most common usage, this method is not overloaded by subclasses,
        as it performs the routing of events to methods. However, this
        method can be overridden if special dispatching rules are needed, or if
        having a single method that catches all events is desired.
        """
        handler_name = 'on_' + (event or '')
        if hasattr(self, handler_name):
            try:
                return getattr(self, handler_name)(*args)
            except TypeError:
                # legacy disconnect events do not have a reason argument
                if event == 'disconnect':
                    return getattr(self, handler_name)(*args[:-1])
                else:  # pragma: no cover
                    raise

    def emit(self, event, data=None, to=None, room=None, skip_sid=None,
             namespace=None, callback=None, ignore_queue=False):
        """Emit a custom event to one or more connected clients.

        The only difference with the :func:`socketio.Server.emit` method is
        that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.server.emit(event, data=data, to=to, room=room,
                                skip_sid=skip_sid,
                                namespace=namespace or self.namespace,
                                callback=callback, ignore_queue=ignore_queue)

    def send(self, data, to=None, room=None, skip_sid=None, namespace=None,
             callback=None, ignore_queue=False):
        """Send a message to one or more connected clients.

        The only difference with the :func:`socketio.Server.send` method is
        that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.server.send(data, to=to, room=room, skip_sid=skip_sid,
                                namespace=namespace or self.namespace,
                                callback=callback, ignore_queue=ignore_queue)

    def call(self, event, data=None, to=None, sid=None, namespace=None,
             timeout=None, ignore_queue=False):
        """Emit a custom event to a client and wait for the response.

        The only difference with the :func:`socketio.Server.call` method is
        that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.server.call(event, data=data, to=to, sid=sid,
                                namespace=namespace or self.namespace,
                                timeout=timeout, ignore_queue=ignore_queue)

    def enter_room(self, sid, room, namespace=None):
        """Enter a room.

        The only difference with the :func:`socketio.Server.enter_room` method
        is that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.server.enter_room(sid, room,
                                      namespace=namespace or self.namespace)

    def leave_room(self, sid, room, namespace=None):
        """Leave a room.

        The only difference with the :func:`socketio.Server.leave_room` method
        is that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.server.leave_room(sid, room,
                                      namespace=namespace or self.namespace)

    def close_room(self, room, namespace=None):
        """Close a room.

        The only difference with the :func:`socketio.Server.close_room` method
        is that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.server.close_room(room,
                                      namespace=namespace or self.namespace)

    def get_session(self, sid, namespace=None):
        """Return the user session for a client.

        The only difference with the :func:`socketio.Server.get_session`
        method is that when the ``namespace`` argument is not given the
        namespace associated with the class is used.
        """
        return self.server.get_session(
            sid, namespace=namespace or self.namespace)

    def save_session(self, sid, session, namespace=None):
        """Store the user session for a client.

        The only difference with the :func:`socketio.Server.save_session`
        method is that when the ``namespace`` argument is not given the
        namespace associated with the class is used.
        """
        return self.server.save_session(
            sid, session, namespace=namespace or self.namespace)

    def session(self, sid, namespace=None):
        """Return the user session for a client with context manager syntax.

        The only difference with the :func:`socketio.Server.session` method is
        that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.server.session(sid, namespace=namespace or self.namespace)

    def disconnect(self, sid, namespace=None):
        """Disconnect a client.

        The only difference with the :func:`socketio.Server.disconnect` method
        is that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.server.disconnect(sid,
                                      namespace=namespace or self.namespace)


class ClientNamespace(base_namespace.BaseClientNamespace):
    """Base class for client-side class-based namespaces.

    A class-based namespace is a class that contains all the event handlers
    for a Socket.IO namespace. The event handlers are methods of the class
    with the prefix ``on_``, such as ``on_connect``, ``on_disconnect``,
    ``on_message``, ``on_json``, and so on.

    :param namespace: The Socket.IO namespace to be used with all the event
                      handlers defined in this class. If this argument is
                      omitted, the default namespace is used.
    """
    def trigger_event(self, event, *args):
        """Dispatch an event to the proper handler method.

        In the most common usage, this method is not overloaded by subclasses,
        as it performs the routing of events to methods. However, this
        method can be overridden if special dispatching rules are needed, or if
        having a single method that catches all events is desired.
        """
        handler_name = 'on_' + (event or '')
        if hasattr(self, handler_name):
            try:
                return getattr(self, handler_name)(*args)
            except TypeError:
                # legacy disconnect events do not have a reason argument
                if event == 'disconnect':
                    return getattr(self, handler_name)(*args[:-1])
                else:  # pragma: no cover
                    raise

    def emit(self, event, data=None, namespace=None, callback=None):
        """Emit a custom event to the server.

        The only difference with the :func:`socketio.Client.emit` method is
        that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.client.emit(event, data=data,
                                namespace=namespace or self.namespace,
                                callback=callback)

    def send(self, data, room=None, namespace=None, callback=None):
        """Send a message to the server.

        The only difference with the :func:`socketio.Client.send` method is
        that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.client.send(data, namespace=namespace or self.namespace,
                                callback=callback)

    def call(self, event, data=None, namespace=None, timeout=None):
        """Emit a custom event to the server and wait for the response.

        The only difference with the :func:`socketio.Client.call` method is
        that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.client.call(event, data=data,
                                namespace=namespace or self.namespace,
                                timeout=timeout)

    def disconnect(self):
        """Disconnect from the server.

        The only difference with the :func:`socketio.Client.disconnect` method
        is that when the ``namespace`` argument is not given the namespace
        associated with the class is used.
        """
        return self.client.disconnect()
