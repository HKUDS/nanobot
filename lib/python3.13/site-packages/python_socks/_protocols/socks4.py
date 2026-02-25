import enum
import ipaddress
import socket
from dataclasses import dataclass
from typing import Optional

from .errors import ReplyError
from .._helpers import is_ipv4_address

RSV = NULL = 0x00
SOCKS_VER = 0x04


class Command(enum.IntEnum):
    CONNECT = 0x01
    BIND = 0x02


class ReplyCode(enum.IntEnum):
    REQUEST_GRANTED = 0x5A
    REQUEST_REJECTED_OR_FAILED = 0x5B
    CONNECTION_FAILED = 0x5C
    AUTHENTICATION_FAILED = 0x5D


ReplyMessages = {
    ReplyCode.REQUEST_GRANTED: 'Request granted',
    ReplyCode.REQUEST_REJECTED_OR_FAILED: 'Request rejected or failed',
    ReplyCode.CONNECTION_FAILED: (
        'Request rejected because SOCKS server cannot connect to identd on the client'
    ),
    ReplyCode.AUTHENTICATION_FAILED: (
        'Request rejected because the client program and identd report different user-ids'
    ),
}


@dataclass
class ConnectRequest:
    host: str  # hostname or IPv4 address
    port: int
    user_id: Optional[str]

    def dumps(self):
        port_bytes = self.port.to_bytes(2, 'big')
        include_hostname = False

        if is_ipv4_address(self.host):
            host_bytes = ipaddress.IPv4Address(self.host).packed
        else:
            include_hostname = True
            host_bytes = bytes([NULL, NULL, NULL, 1])

        data = bytearray([SOCKS_VER, Command.CONNECT])
        data += port_bytes
        data += host_bytes

        if self.user_id:
            data += self.user_id.encode('ascii')

        data.append(NULL)

        if include_hostname:
            data += self.host.encode('idna')
            data.append(NULL)

        return bytes(data)


@dataclass
class ConnectReply:
    SIZE = 8

    rsv: int
    reply: ReplyCode
    host: str  # should be ignored when using Command.CONNECT
    port: int  # should be ignored when using Command.CONNECT

    @classmethod
    def loads(cls, data: bytes) -> 'ConnectReply':
        if len(data) != cls.SIZE:
            raise ReplyError('Malformed connect reply')

        rsv = data[0]
        if rsv != RSV:  # pragma: no cover
            raise ReplyError(f'Unexpected reply version: {data[0]:#02X}')

        try:
            reply = ReplyCode(data[1])
        except ValueError:
            raise ReplyError(f'Invalid reply code: {data[1]:#02X}')

        if reply != ReplyCode.REQUEST_GRANTED:  # pragma: no cover
            msg = ReplyMessages.get(reply, 'Unknown error')
            raise ReplyError(msg, error_code=reply)

        try:
            port = int.from_bytes(data[2:4], byteorder="big")
        except ValueError:
            raise ReplyError('Invalid port data')

        try:
            host = socket.inet_ntop(socket.AF_INET, data[4:8])
        except ValueError:
            raise ReplyError('Invalid port data')

        return cls(rsv=rsv, reply=reply, host=host, port=port)


# noinspection PyMethodMayBeStatic
class Connection:
    def send(self, request: ConnectRequest) -> bytes:
        return request.dumps()

    def receive(self, data: bytes) -> ConnectReply:
        return ConnectReply.loads(data)
