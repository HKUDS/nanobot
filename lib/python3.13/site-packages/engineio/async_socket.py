import asyncio
import sys
import time

from . import base_socket
from . import exceptions
from . import packet
from . import payload


class AsyncSocket(base_socket.BaseSocket):
    async def poll(self):
        """Wait for packets to send to the client."""
        try:
            packets = [await asyncio.wait_for(
                self.queue.get(),
                self.server.ping_interval + self.server.ping_timeout)]
            self.queue.task_done()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            raise exceptions.QueueEmpty()
        if packets == [None]:
            return []
        while True:
            try:
                pkt = self.queue.get_nowait()
                self.queue.task_done()
                if pkt is None:
                    self.queue.put_nowait(None)
                    break
                packets.append(pkt)
            except asyncio.QueueEmpty:
                break
        return packets

    async def receive(self, pkt):
        """Receive packet from the client."""
        self.server.logger.info('%s: Received packet %s data %s',
                                self.sid, packet.packet_names[pkt.packet_type],
                                pkt.data if not isinstance(pkt.data, bytes)
                                else '<binary>')
        if pkt.packet_type == packet.PONG:
            self.schedule_ping()
        elif pkt.packet_type == packet.MESSAGE:
            await self.server._trigger_event(
                'message', self.sid, pkt.data,
                run_async=self.server.async_handlers)
        elif pkt.packet_type == packet.UPGRADE:
            await self.send(packet.Packet(packet.NOOP))
        elif pkt.packet_type == packet.CLOSE:
            await self.close(wait=False, abort=True,
                             reason=self.server.reason.CLIENT_DISCONNECT)
        else:
            raise exceptions.UnknownPacketError()

    async def check_ping_timeout(self):
        """Make sure the client is still sending pings."""
        if self.closed:
            raise exceptions.SocketIsClosedError()
        if self.last_ping and \
                time.time() - self.last_ping > self.server.ping_timeout:
            self.server.logger.info('%s: Client is gone, closing socket',
                                    self.sid)
            # Passing abort=False here will cause close() to write a
            # CLOSE packet. This has the effect of updating half-open sockets
            # to their correct state of disconnected
            await self.close(wait=False, abort=False,
                             reason=self.server.reason.PING_TIMEOUT)
            return False
        return True

    async def send(self, pkt):
        """Send a packet to the client."""
        if not await self.check_ping_timeout():
            return
        else:
            await self.queue.put(pkt)
        self.server.logger.info('%s: Sending packet %s data %s',
                                self.sid, packet.packet_names[pkt.packet_type],
                                pkt.data if not isinstance(pkt.data, bytes)
                                else '<binary>')

    async def handle_get_request(self, environ):
        """Handle a long-polling GET request from the client."""
        connections = [
            s.strip()
            for s in environ.get('HTTP_CONNECTION', '').lower().split(',')]
        transport = environ.get('HTTP_UPGRADE', '').lower()
        if 'upgrade' in connections and transport in self.upgrade_protocols:
            self.server.logger.info('%s: Received request to upgrade to %s',
                                    self.sid, transport)
            return await getattr(self, '_upgrade_' + transport)(environ)
        if self.upgrading or self.upgraded:
            # we are upgrading to WebSocket, do not return any more packets
            # through the polling endpoint
            return [packet.Packet(packet.NOOP)]
        try:
            packets = await self.poll()
        except exceptions.QueueEmpty:
            exc = sys.exc_info()
            await self.close(wait=False,
                             reason=self.server.reason.TRANSPORT_ERROR)
            raise exc[1].with_traceback(exc[2])
        return packets

    async def handle_post_request(self, environ):
        """Handle a long-polling POST request from the client."""
        length = int(environ.get('CONTENT_LENGTH', '0'))
        if length > self.server.max_http_buffer_size:
            raise exceptions.ContentTooLongError()
        else:
            body = (await environ['wsgi.input'].read(length)).decode('utf-8')
            p = payload.Payload(encoded_payload=body)
            for pkt in p.packets:
                await self.receive(pkt)

    async def close(self, wait=True, abort=False, reason=None):
        """Close the socket connection."""
        if not self.closed and not self.closing:
            self.closing = True
            await self.server._trigger_event(
                'disconnect', self.sid,
                reason or self.server.reason.SERVER_DISCONNECT,
                run_async=False)
            if not abort:
                await self.send(packet.Packet(packet.CLOSE))
            self.closed = True
            if wait:
                await self.queue.join()

    def schedule_ping(self):
        self.server.start_background_task(self._send_ping)

    async def _send_ping(self):
        self.last_ping = None
        await asyncio.sleep(self.server.ping_interval)
        if not self.closing and not self.closed:
            self.last_ping = time.time()
            await self.send(packet.Packet(packet.PING))

    async def _upgrade_websocket(self, environ):
        """Upgrade the connection from polling to websocket."""
        if self.upgraded:
            raise OSError('Socket has been upgraded already')
        if self.server._async['websocket'] is None:
            # the selected async mode does not support websocket
            return self.server._bad_request()
        ws = self.server._async['websocket'](
            self._websocket_handler, self.server)
        return await ws(environ)

    async def _websocket_handler(self, ws):
        """Engine.IO handler for websocket transport."""
        async def websocket_wait():
            data = await ws.wait()
            if data and len(data) > self.server.max_http_buffer_size:
                raise ValueError('packet is too large')
            return data

        if self.connected:
            # the socket was already connected, so this is an upgrade
            self.upgrading = True  # hold packet sends during the upgrade

            try:
                pkt = await websocket_wait()
            except OSError:  # pragma: no cover
                return
            decoded_pkt = packet.Packet(encoded_packet=pkt)
            if decoded_pkt.packet_type != packet.PING or \
                    decoded_pkt.data != 'probe':
                self.server.logger.info(
                    '%s: Failed websocket upgrade, no PING packet', self.sid)
                self.upgrading = False
                return
            await ws.send(packet.Packet(packet.PONG, data='probe').encode())
            await self.queue.put(packet.Packet(packet.NOOP))  # end poll

            try:
                pkt = await websocket_wait()
            except OSError:  # pragma: no cover
                self.upgrading = False
                return
            decoded_pkt = packet.Packet(encoded_packet=pkt)
            if decoded_pkt.packet_type != packet.UPGRADE:
                self.upgraded = False
                self.server.logger.info(
                    ('%s: Failed websocket upgrade, expected UPGRADE packet, '
                     'received %s instead.'),
                    self.sid, pkt)
                self.upgrading = False
                return
            self.upgraded = True
            self.upgrading = False
        else:
            self.connected = True
            self.upgraded = True

        # start separate writer thread
        async def writer():
            while True:
                packets = None
                try:
                    packets = await self.poll()
                except exceptions.QueueEmpty:
                    break
                if not packets:
                    # empty packet list returned -> connection closed
                    break
                try:
                    for pkt in packets:
                        await ws.send(pkt.encode())
                except:
                    break
            await ws.close()

        writer_task = asyncio.ensure_future(writer())

        self.server.logger.info(
            '%s: Upgrade to websocket successful', self.sid)

        while True:
            p = None
            wait_task = asyncio.ensure_future(websocket_wait())
            try:
                p = await asyncio.wait_for(
                    wait_task,
                    self.server.ping_interval + self.server.ping_timeout)
            except asyncio.CancelledError:  # pragma: no cover
                # there is a bug (https://bugs.python.org/issue30508) in
                # asyncio that causes a "Task exception never retrieved" error
                # to appear when wait_task raises an exception before it gets
                # cancelled. Calling wait_task.exception() prevents the error
                # from being issued in Python 3.6, but causes other errors in
                # other versions, so we run it with all errors suppressed and
                # hope for the best.
                try:
                    wait_task.exception()
                except:
                    pass
                break
            except:
                break
            if p is None:
                # connection closed by client
                break
            pkt = packet.Packet(encoded_packet=p)
            try:
                await self.receive(pkt)
            except exceptions.UnknownPacketError:  # pragma: no cover
                pass
            except exceptions.SocketIsClosedError:  # pragma: no cover
                self.server.logger.info('Receive error -- socket is closed')
                break
            except:  # pragma: no cover
                # if we get an unexpected exception we log the error and exit
                # the connection properly
                self.server.logger.exception('Unknown receive error')

        await self.queue.put(None)  # unlock the writer task so it can exit
        await asyncio.wait_for(writer_task, timeout=None)
        await self.close(wait=False, abort=True,
                         reason=self.server.reason.TRANSPORT_CLOSE)
