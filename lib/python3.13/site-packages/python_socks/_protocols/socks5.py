import enum
import ipaddress
import socket
from typing import Optional, Union
from dataclasses import dataclass, field

from .errors import ReplyError
from .._helpers import is_ip_address


RSV = NULL = AUTH_GRANTED = 0x00
SOCKS_VER = 0x05


class AuthMethod(enum.IntEnum):
    ANONYMOUS = 0x00
    GSSAPI = 0x01
    USERNAME_PASSWORD = 0x02
    NO_ACCEPTABLE = 0xFF


class AddressType(enum.IntEnum):
    IPV4 = 0x01
    DOMAIN = 0x03
    IPV6 = 0x04

    @classmethod
    def from_ip_ver(cls, ver: int):
        if ver == 4:
            return cls.IPV4
        if ver == 6:
            return cls.IPV6

        raise ValueError('Invalid IP version')


class Command(enum.IntEnum):
    CONNECT = 0x01
    BIND = 0x02
    UDP_ASSOCIATE = 0x03


class ReplyCode(enum.IntEnum):
    SUCCEEDED = 0x00
    GENERAL_FAILURE = 0x01
    CONNECTION_NOT_ALLOWED = 0x02
    NETWORK_UNREACHABLE = 0x03
    HOST_UNREACHABLE = 0x04
    CONNECTION_REFUSED = 0x05
    TTL_EXPIRED = 0x06
    COMMAND_NOT_SUPPORTED = 0x07
    ADDRESS_TYPE_NOT_SUPPORTED = 0x08


ReplyMessages = {
    ReplyCode.SUCCEEDED: 'Request granted',
    ReplyCode.GENERAL_FAILURE: 'General SOCKS server failure',
    ReplyCode.CONNECTION_NOT_ALLOWED: 'Connection not allowed by ruleset',
    ReplyCode.NETWORK_UNREACHABLE: 'Network unreachable',
    ReplyCode.HOST_UNREACHABLE: 'Host unreachable',
    ReplyCode.CONNECTION_REFUSED: 'Connection refused by destination host',
    ReplyCode.TTL_EXPIRED: 'TTL expired',
    ReplyCode.COMMAND_NOT_SUPPORTED: 'Command not supported or protocol error',
    ReplyCode.ADDRESS_TYPE_NOT_SUPPORTED: 'Address type not supported',
}


@dataclass
class AuthMethodsRequest:
    username: Optional[str]
    password: Optional[str]
    methods: bytearray = field(init=False)

    def __post_init__(self):
        methods = bytearray([AuthMethod.ANONYMOUS])

        if self.username and self.password:
            methods.append(AuthMethod.USERNAME_PASSWORD)

        self.methods = methods

    def dumps(self) -> bytes:
        return bytes([SOCKS_VER, len(self.methods)]) + self.methods


@dataclass
class AuthMethodReply:
    SIZE = 2

    ver: int
    method: AuthMethod

    def validate(self, request: AuthMethodsRequest):
        if self.method not in request.methods:  # pragma: no cover
            raise ReplyError(f'Unexpected SOCKS authentication method: {self.method}')

    @classmethod
    def loads(cls, data: bytes) -> 'AuthMethodReply':
        if len(data) != cls.SIZE:
            raise ReplyError('Malformed authentication method reply')

        ver = data[0]
        if ver != SOCKS_VER:  # pragma: no cover
            raise ReplyError(f'Unexpected SOCKS version number: {ver}')

        try:
            method = AuthMethod(data[1])
        except ValueError:
            raise ReplyError(f'Invalid authentication method: {data[1]:#02X}')

        if method == AuthMethod.NO_ACCEPTABLE:  # pragma: no cover
            raise ReplyError('No acceptable authentication methods were offered')

        return cls(ver=ver, method=method)


@dataclass
class AuthRequest:
    VER = 0x01

    username: str
    password: str

    def dumps(self) -> bytes:
        data = bytearray()
        data.append(self.VER)
        data.append(len(self.username))
        data += self.username.encode('ascii')
        data.append(len(self.password))
        data += self.password.encode('ascii')
        return bytes(data)


@dataclass
class AuthReply:
    SIZE = 2

    ver: int
    status: int

    @classmethod
    def loads(cls, data: bytes) -> 'AuthReply':
        if len(data) != cls.SIZE:
            raise ReplyError('Malformed auth reply')

        ver = data[0]
        if ver != AuthRequest.VER:  # pragma: no cover
            raise ReplyError('Invalid authentication response')

        status = data[1]
        if status != AUTH_GRANTED:  # pragma: no cover
            raise ReplyError('Username and password authentication failure')

        return cls(ver=ver, status=status)


@dataclass
class ConnectRequest:
    host: str  # hostname or IPv4 or IPv6 address
    port: int

    def dumps(self) -> bytes:
        data = bytearray([SOCKS_VER, Command.CONNECT, RSV])
        data += self._build_addr_request()
        return bytes(data)

    def _build_addr_request(self) -> bytes:
        port = self.port.to_bytes(2, 'big')

        if is_ip_address(self.host):
            ip = ipaddress.ip_address(self.host)
            address_type = AddressType.from_ip_ver(ip.version)
            return bytes([address_type]) + ip.packed + port
        else:
            address_type = AddressType.DOMAIN
            host = self.host.encode('idna')
            return bytes([address_type, len(host)]) + host + port


@dataclass
class ConnectReply:
    ver: int
    reply: ReplyCode
    rsv: int
    bound_host: str
    bound_port: int

    def validate(self):
        pass

    @classmethod
    def loads(cls, data: bytes) -> 'ConnectReply':
        if not data:
            raise ReplyError('Empty connect reply')

        ver = data[0]
        if ver != SOCKS_VER:  # pragma: no cover
            raise ReplyError(f'Unexpected SOCKS version number: {ver:#02X}')

        try:
            reply = ReplyCode(data[1])
        except IndexError:
            raise ReplyError('Malformed connect reply')
        except ValueError:
            raise ReplyError(f'Invalid reply code: {data[1]:#02X}')

        if reply != ReplyCode.SUCCEEDED:  # pragma: no cover
            msg = ReplyMessages.get(reply, 'Unknown error')  # type: ignore
            raise ReplyError(msg, error_code=reply)

        try:
            rsv = data[2]
        except IndexError:
            raise ReplyError('Malformed connect reply')

        if rsv != RSV:  # pragma: no cover
            raise ReplyError(f'The reserved byte must be {RSV:#02X}')

        try:
            addr_type = data[3]
            bnd_host_data = data[4:-2]
            bnd_port_data = data[-2:]
        except IndexError:
            raise ReplyError('Malformed connect reply')

        if addr_type == AddressType.IPV4:
            bnd_host = socket.inet_ntop(socket.AF_INET, bnd_host_data)
        elif addr_type == AddressType.IPV6:
            bnd_host = socket.inet_ntop(socket.AF_INET6, bnd_host_data)
        elif addr_type == AddressType.DOMAIN:  # pragma: no cover
            # host_len = bnd_host_data[0]
            bnd_host = bnd_host_data[1:].decode()
        else:  # pragma: no cover
            raise ReplyError(f'Invalid address type: {addr_type:#02X}')

        bnd_port = int.from_bytes(bnd_port_data, 'big')

        return cls(
            ver=ver,
            reply=reply,
            rsv=rsv,
            bound_host=bnd_host,
            bound_port=bnd_port,
        )


class StateServerWaitingForAuthMethods:
    pass


@dataclass
class StateClientSentAuthMethods:
    data: AuthMethodsRequest


@dataclass
class StateServerWaitingForAuth:
    data: AuthMethodReply


@dataclass
class StateClientAuthenticated:
    data: Optional[AuthReply] = None


@dataclass
class StateClientSentAuthRequest:
    data: AuthRequest


@dataclass
class StateClientSentConnectRequest:
    data: ConnectRequest


@dataclass
class StateServerConnected:
    data: ConnectReply


Request = Union[
    AuthMethodsRequest,
    AuthRequest,
    ConnectRequest,
]

Reply = Union[
    AuthMethodReply,
    AuthReply,
    ConnectReply,
]

ConnectionState = Union[
    StateServerWaitingForAuthMethods,
    StateClientSentAuthMethods,
    StateServerWaitingForAuth,
    StateClientSentAuthRequest,
    StateClientAuthenticated,
    StateClientSentConnectRequest,
    StateServerConnected,
]


class Connection:
    _state: ConnectionState

    def __init__(self):
        self._state = StateServerWaitingForAuthMethods()

    def send(self, request: Request) -> bytes:
        if type(request) is AuthMethodsRequest:
            if type(self._state) is not StateServerWaitingForAuthMethods:
                raise RuntimeError('Server is not currently waiting for auth methods')
            self._state = StateClientSentAuthMethods(request)
            return request.dumps()

        if type(request) is AuthRequest:
            if type(self._state) is not StateServerWaitingForAuth:
                raise RuntimeError('Server is not currently waiting for authentication')
            self._state = StateClientSentAuthRequest(request)
            return request.dumps()

        if type(request) is ConnectRequest:
            if type(self._state) is not StateClientAuthenticated:
                raise RuntimeError('Client is not authenticated')
            self._state = StateClientSentConnectRequest(request)
            return request.dumps()

        raise RuntimeError(f'Invalid request type: {type(request)}')

    def receive(self, data: bytes) -> Reply:
        if type(self._state) is StateClientSentAuthMethods:
            reply = AuthMethodReply.loads(data)
            reply.validate(self._state.data)
            if reply.method == AuthMethod.USERNAME_PASSWORD:
                self._state = StateServerWaitingForAuth(data=reply)
            else:
                self._state = StateClientAuthenticated()
            return reply

        if type(self._state) is StateClientSentAuthRequest:
            reply = AuthReply.loads(data)
            self._state = StateClientAuthenticated(data=reply)
            return reply

        if type(self._state) is StateClientSentConnectRequest:
            reply = ConnectReply.loads(data)
            self._state = StateServerConnected(data=reply)
            return reply

        raise RuntimeError(f'Invalid connection state: {self._state}')

    @property
    def state(self):
        return self._state
