import sys
import time

from . import base_socket
from . import exceptions
from . import packet
from . import payload


class Socket(base_socket.BaseSocket):
    """An Engine.IO socket."""
    def poll(self):
        """Wait for packets to send to the client."""
        queue_empty = self.server.get_queue_empty_exception()
        try:
            packets = [self.queue.get(
                timeout=self.server.ping_interval + self.server.ping_timeout)]
            self.queue.task_done()
        except queue_empty:
            raise exceptions.QueueEmpty()
        if packets == [None]:
            return []
        while True:
            try:
                pkt = self.queue.get(block=False)
                self.queue.task_done()
                if pkt is None:
                    self.queue.put(None)
                    break
                packets.append(pkt)
            except queue_empty:
                break
        return packets

    def receive(self, pkt):
        """Receive packet from the client."""
        packet_name = packet.packet_names[pkt.packet_type] \
            if pkt.packet_type < len(packet.packet_names) else 'UNKNOWN'
        self.server.logger.info('%s: Received packet %s data %s',
                                self.sid, packet_name,
                                pkt.data if not isinstance(pkt.data, bytes)
                                else '<binary>')
        if pkt.packet_type == packet.PONG:
            self.schedule_ping()
        elif pkt.packet_type == packet.MESSAGE:
            self.server._trigger_event('message', self.sid, pkt.data,
                                       run_async=self.server.async_handlers)
        elif pkt.packet_type == packet.UPGRADE:
            self.send(packet.Packet(packet.NOOP))
        elif pkt.packet_type == packet.CLOSE:
            self.close(wait=False, abort=True,
                       reason=self.server.reason.CLIENT_DISCONNECT)
        else:
            raise exceptions.UnknownPacketError()

    def check_ping_timeout(self):
        """Make sure the client is still responding to pings."""
        if self.closed:
            raise exceptions.SocketIsClosedError()
        if self.last_ping and \
                time.time() - self.last_ping > self.server.ping_timeout:
            self.server.logger.info('%s: Client is gone, closing socket',
                                    self.sid)
            # Passing abort=False here will cause close() to write a
            # CLOSE packet. This has the effect of updating half-open sockets
            # to their correct state of disconnected
            self.close(wait=False, abort=False,
                       reason=self.server.reason.PING_TIMEOUT)
            return False
        return True

    def send(self, pkt):
        """Send a packet to the client."""
        if not self.check_ping_timeout():
            return
        else:
            self.queue.put(pkt)
        self.server.logger.info('%s: Sending packet %s data %s',
                                self.sid, packet.packet_names[pkt.packet_type],
                                pkt.data if not isinstance(pkt.data, bytes)
                                else '<binary>')

    def handle_get_request(self, environ, start_response):
        """Handle a long-polling GET request from the client."""
        connections = [
            s.strip()
            for s in environ.get('HTTP_CONNECTION', '').lower().split(',')]
        transport = environ.get('HTTP_UPGRADE', '').lower()
        if 'upgrade' in connections and transport in self.upgrade_protocols:
            self.server.logger.info('%s: Received request to upgrade to %s',
                                    self.sid, transport)
            return getattr(self, '_upgrade_' + transport)(environ,
                                                          start_response)
        if self.upgrading or self.upgraded:
            # we are upgrading to WebSocket, do not return any more packets
            # through the polling endpoint
            return [packet.Packet(packet.NOOP)]
        try:
            packets = self.poll()
        except exceptions.QueueEmpty:
            exc = sys.exc_info()
            self.close(wait=False, reason=self.server.reason.TRANSPORT_ERROR)
            raise exc[1].with_traceback(exc[2])
        return packets

    def handle_post_request(self, environ):
        """Handle a long-polling POST request from the client."""
        length = int(environ.get('CONTENT_LENGTH', '0'))
        if length > self.server.max_http_buffer_size:
            raise exceptions.ContentTooLongError()
        else:
            body = environ['wsgi.input'].read(length).decode('utf-8')
            p = payload.Payload(encoded_payload=body)
            for pkt in p.packets:
                self.receive(pkt)

    def close(self, wait=True, abort=False, reason=None):
        """Close the socket connection."""
        if not self.closed and not self.closing:
            self.closing = True
            self.server._trigger_event(
                'disconnect', self.sid,
                reason or self.server.reason.SERVER_DISCONNECT,
                run_async=False)
            if not abort:
                self.send(packet.Packet(packet.CLOSE))
            self.closed = True
            self.queue.put(None)
            if wait:
                self.queue.join()

    def schedule_ping(self):
        self.server.start_background_task(self._send_ping)

    def _send_ping(self):
        self.last_ping = None
        self.server.sleep(self.server.ping_interval)
        if not self.closing and not self.closed:
            self.last_ping = time.time()
            self.send(packet.Packet(packet.PING))

    def _upgrade_websocket(self, environ, start_response):
        """Upgrade the connection from polling to websocket."""
        if self.upgraded:
            raise OSError('Socket has been upgraded already')
        if self.server._async['websocket'] is None:
            # the selected async mode does not support websocket
            return self.server._bad_request()
        ws = self.server._async['websocket'](
            self._websocket_handler, self.server)
        return ws(environ, start_response)

    def _websocket_handler(self, ws):
        """Engine.IO handler for websocket transport."""
        def websocket_wait():
            data = ws.wait()
            if data and len(data) > self.server.max_http_buffer_size:
                raise ValueError('packet is too large')
            return data

        # try to set a socket timeout matching the configured ping interval
        # and timeout
        for attr in ['_sock', 'socket']:  # pragma: no cover
            if hasattr(ws, attr) and hasattr(getattr(ws, attr), 'settimeout'):
                getattr(ws, attr).settimeout(
                    self.server.ping_interval + self.server.ping_timeout)

        if self.connected:
            # the socket was already connected, so this is an upgrade
            self.upgrading = True  # hold packet sends during the upgrade

            pkt = websocket_wait()
            decoded_pkt = packet.Packet(encoded_packet=pkt)
            if decoded_pkt.packet_type != packet.PING or \
                    decoded_pkt.data != 'probe':
                self.server.logger.info(
                    '%s: Failed websocket upgrade, no PING packet', self.sid)
                self.upgrading = False
                return []
            ws.send(packet.Packet(packet.PONG, data='probe').encode())
            self.queue.put(packet.Packet(packet.NOOP))  # end poll

            pkt = websocket_wait()
            decoded_pkt = packet.Packet(encoded_packet=pkt)
            if decoded_pkt.packet_type != packet.UPGRADE:
                self.upgraded = False
                self.server.logger.info(
                    ('%s: Failed websocket upgrade, expected UPGRADE packet, '
                     'received %s instead.'),
                    self.sid, pkt)
                self.upgrading = False
                return []
            self.upgraded = True
            self.upgrading = False
        else:
            self.connected = True
            self.upgraded = True

        # start separate writer thread
        def writer():
            while True:
                packets = None
                try:
                    packets = self.poll()
                except exceptions.QueueEmpty:
                    break
                if not packets:
                    # empty packet list returned -> connection closed
                    break
                try:
                    for pkt in packets:
                        ws.send(pkt.encode())
                except:
                    break
            ws.close()

        writer_task = self.server.start_background_task(writer)

        self.server.logger.info(
            '%s: Upgrade to websocket successful', self.sid)

        while True:
            p = None
            try:
                p = websocket_wait()
            except Exception as e:
                # if the socket is already closed, we can assume this is a
                # downstream error of that
                if not self.closed:  # pragma: no cover
                    self.server.logger.info(
                        '%s: Unexpected error "%s", closing connection',
                        self.sid, str(e))
                break
            if p is None:
                # connection closed by client
                break
            pkt = packet.Packet(encoded_packet=p)
            try:
                self.receive(pkt)
            except exceptions.UnknownPacketError:  # pragma: no cover
                pass
            except exceptions.SocketIsClosedError:  # pragma: no cover
                self.server.logger.info('Receive error -- socket is closed')
                break
            except:  # pragma: no cover
                # if we get an unexpected exception we log the error and exit
                # the connection properly
                self.server.logger.exception('Unknown receive error')
                break

        self.queue.put(None)  # unlock the writer task so that it can exit
        writer_task.join()
        self.close(wait=False, abort=True,
                   reason=self.server.reason.TRANSPORT_CLOSE)

        return []
