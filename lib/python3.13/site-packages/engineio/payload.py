import urllib

from . import packet


class Payload:
    """Engine.IO payload."""
    max_decode_packets = 16

    def __init__(self, packets=None, encoded_payload=None):
        self.packets = packets or []
        if encoded_payload is not None:
            self.decode(encoded_payload)

    def encode(self, jsonp_index=None):
        """Encode the payload for transmission."""
        encoded_payload = ''
        for pkt in self.packets:
            if encoded_payload:
                encoded_payload += '\x1e'
            encoded_payload += pkt.encode(b64=True)
        if jsonp_index is not None:
            encoded_payload = '___eio[' + \
                              str(jsonp_index) + \
                              ']("' + \
                              encoded_payload.replace('"', '\\"') + \
                              '");'
        return encoded_payload

    def decode(self, encoded_payload):
        """Decode a transmitted payload."""
        self.packets = []

        if len(encoded_payload) == 0:
            return

        # JSONP POST payload starts with 'd='
        if encoded_payload.startswith('d='):
            encoded_payload = urllib.parse.parse_qs(
                encoded_payload)['d'][0]

        encoded_packets = encoded_payload.split('\x1e')
        if len(encoded_packets) > self.max_decode_packets:
            raise ValueError('Too many packets in payload')
        self.packets = [packet.Packet(encoded_packet=encoded_packet)
                        for encoded_packet in encoded_packets]
