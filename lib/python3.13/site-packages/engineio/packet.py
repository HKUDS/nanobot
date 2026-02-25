import base64
from engineio import json as _json

(OPEN, CLOSE, PING, PONG, MESSAGE, UPGRADE, NOOP) = (0, 1, 2, 3, 4, 5, 6)
packet_names = ['OPEN', 'CLOSE', 'PING', 'PONG', 'MESSAGE', 'UPGRADE', 'NOOP']

binary_types = (bytes, bytearray)


class Packet:
    """Engine.IO packet."""

    json = _json

    def __init__(self, packet_type=NOOP, data=None, encoded_packet=None):
        self.packet_type = packet_type
        self.data = data
        self.encode_cache = None
        if isinstance(data, str):
            self.binary = False
        elif isinstance(data, binary_types):
            self.binary = True
        else:
            self.binary = False
        if self.binary and self.packet_type != MESSAGE:
            raise ValueError('Binary packets can only be of type MESSAGE')
        if encoded_packet is not None:
            self.decode(encoded_packet)

    def encode(self, b64=False):
        """Encode the packet for transmission.

        Note: as a performance optimization, subsequent calls to this method
        will return a cached encoded packet, even if the data has changed.
        """
        if self.encode_cache:
            return self.encode_cache
        if self.binary:
            if b64:
                encoded_packet = 'b' + base64.b64encode(self.data).decode(
                    'utf-8')
            else:
                encoded_packet = self.data
        else:
            encoded_packet = str(self.packet_type)
            if isinstance(self.data, str):
                encoded_packet += self.data
            elif isinstance(self.data, dict) or isinstance(self.data, list):
                encoded_packet += self.json.dumps(self.data,
                                                  separators=(',', ':'))
            elif self.data is not None:
                encoded_packet += str(self.data)
        self.encode_cache = encoded_packet
        return encoded_packet

    def decode(self, encoded_packet):
        """Decode a transmitted package."""
        self.binary = isinstance(encoded_packet, binary_types)
        if not self.binary and len(encoded_packet) == 0:
            raise ValueError('Invalid empty packet received')
        b64 = not self.binary and encoded_packet[0] == 'b'
        if b64:
            self.binary = True
            self.packet_type = MESSAGE
            self.data = base64.b64decode(encoded_packet[1:])
        else:
            if self.binary and not isinstance(encoded_packet, bytes):
                encoded_packet = bytes(encoded_packet)
            if self.binary:
                self.packet_type = MESSAGE
                self.data = encoded_packet
            else:
                self.packet_type = int(encoded_packet[0])
                try:
                    if encoded_packet[1].isnumeric():
                        # do not allow integer payloads, see
                        # github.com/miguelgrinberg/python-engineio/issues/75
                        # for background on this decision
                        raise ValueError
                    self.data = self.json.loads(encoded_packet[1:])
                except (ValueError, IndexError):
                    self.data = encoded_packet[1:]
