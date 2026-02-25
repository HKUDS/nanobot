import functools
from engineio import json as _json

(CONNECT, DISCONNECT, EVENT, ACK, CONNECT_ERROR, BINARY_EVENT, BINARY_ACK) = \
    (0, 1, 2, 3, 4, 5, 6)
packet_names = ['CONNECT', 'DISCONNECT', 'EVENT', 'ACK', 'CONNECT_ERROR',
                'BINARY_EVENT', 'BINARY_ACK']


class Packet:
    """Socket.IO packet."""

    # the format of the Socket.IO packet is as follows:
    #
    # packet type: 1 byte, values 0-6
    # num_attachments: ASCII encoded, only if num_attachments != 0
    # '-': only if num_attachments != 0
    # namespace, followed by a ',': only if namespace != '/'
    # id: ASCII encoded, only if id is not None
    # data: JSON dump of data payload

    uses_binary_events = True
    json = _json

    def __init__(self, packet_type=EVENT, data=None, namespace=None, id=None,
                 binary=None, encoded_packet=None):
        self.packet_type = packet_type
        self.data = data
        self.namespace = namespace
        self.id = id
        if self.uses_binary_events and \
                (binary or (binary is None and self.data_is_binary(
                    self.data))):
            if self.packet_type == EVENT:
                self.packet_type = BINARY_EVENT
            elif self.packet_type == ACK:
                self.packet_type = BINARY_ACK
            else:
                raise ValueError('Packet does not support binary payload.')
        self.attachment_count = 0
        self.attachments = []
        if encoded_packet:
            self.attachment_count = self.decode(encoded_packet) or 0

    def encode(self):
        """Encode the packet for transmission.

        If the packet contains binary elements, this function returns a list
        of packets where the first is the original packet with placeholders for
        the binary components and the remaining ones the binary attachments.
        """
        encoded_packet = str(self.packet_type)
        if self.packet_type == BINARY_EVENT or self.packet_type == BINARY_ACK:
            data, attachments = self.deconstruct_binary(self.data)
            encoded_packet += str(len(attachments)) + '-'
        else:
            data = self.data
            attachments = None
        if self.namespace is not None and self.namespace != '/':
            encoded_packet += self.namespace + ','
        if self.id is not None:
            encoded_packet += str(self.id)
        if data is not None:
            encoded_packet += self.json.dumps(data, separators=(',', ':'))
        if attachments is not None:
            encoded_packet = [encoded_packet] + attachments
        return encoded_packet

    def decode(self, encoded_packet):
        """Decode a transmitted package.

        The return value indicates how many binary attachment packets are
        necessary to fully decode the packet.
        """
        ep = encoded_packet
        try:
            self.packet_type = int(ep[0:1])
        except TypeError:
            self.packet_type = ep
            ep = ''
        self.namespace = None
        self.data = None
        ep = ep[1:]
        dash = ep.find('-')
        attachment_count = 0
        if dash > 0 and ep[0:dash].isdigit():
            if dash > 10:
                raise ValueError('too many attachments')
            attachment_count = int(ep[0:dash])
            ep = ep[dash + 1:]
        if ep and ep[0:1] == '/':
            sep = ep.find(',')
            if sep == -1:
                self.namespace = ep
                ep = ''
            else:
                self.namespace = ep[0:sep]
                ep = ep[sep + 1:]
            q = self.namespace.find('?')
            if q != -1:
                self.namespace = self.namespace[0:q]
        if ep and ep[0].isdigit():
            i = 1
            end = len(ep)
            while i < end:
                if not ep[i].isdigit() or i >= 100:
                    break
                i += 1
            self.id = int(ep[:i])
            ep = ep[i:]
            if len(ep) > 0 and ep[0].isdigit():
                raise ValueError('id field is too long')
        if ep:
            self.data = self.json.loads(ep)
        return attachment_count

    def add_attachment(self, attachment):
        if self.attachment_count <= len(self.attachments):
            raise ValueError('Unexpected binary attachment')
        self.attachments.append(attachment)
        if self.attachment_count == len(self.attachments):
            self.data = self.reconstruct_binary(self.data, self.attachments)
            return True
        return False

    @classmethod
    def reconstruct_binary(cls, data, attachments):
        """Reconstruct a decoded packet using the given list of binary
        attachments.
        """
        return cls._reconstruct_binary_internal(data, attachments)

    @classmethod
    def _reconstruct_binary_internal(cls, data, attachments):
        if isinstance(data, list):
            return [cls._reconstruct_binary_internal(item, attachments)
                    for item in data]
        elif isinstance(data, dict):
            if data.get('_placeholder') and 'num' in data:
                return attachments[data['num']]
            else:
                return {key: cls._reconstruct_binary_internal(value,
                                                              attachments)
                        for key, value in data.items()}
        else:
            return data

    @classmethod
    def deconstruct_binary(cls, data):
        """Extract binary components in the packet."""
        attachments = []
        data = cls._deconstruct_binary_internal(data, attachments)
        return data, attachments

    @classmethod
    def _deconstruct_binary_internal(cls, data, attachments):
        if isinstance(data, (bytes, bytearray)):
            attachments.append(data)
            return {'_placeholder': True, 'num': len(attachments) - 1}
        elif isinstance(data, list):
            return [cls._deconstruct_binary_internal(item, attachments)
                    for item in data]
        elif isinstance(data, dict):
            return {key: cls._deconstruct_binary_internal(value, attachments)
                    for key, value in data.items()}
        else:
            return data

    @classmethod
    def data_is_binary(cls, data):
        """Check if the data contains binary components."""
        if isinstance(data, (bytes, bytearray)):
            return True
        elif isinstance(data, list):
            return functools.reduce(
                lambda a, b: a or b, [cls.data_is_binary(item)
                                      for item in data], False)
        elif isinstance(data, dict):
            return functools.reduce(
                lambda a, b: a or b, [cls.data_is_binary(item)
                                      for item in data.values()],
                False)
        else:
            return False

    def _to_dict(self):
        d = {
            'type': self.packet_type,
            'data': self.data,
            'nsp': self.namespace,
        }
        if self.id is not None:
            d['id'] = self.id
        return d
