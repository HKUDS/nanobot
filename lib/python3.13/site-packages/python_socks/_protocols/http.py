import sys
from dataclasses import dataclass
import base64
import binascii
from collections import namedtuple
from typing import Optional

from .._version import __title__, __version__

from .errors import ReplyError

DEFAULT_USER_AGENT = 'Python/{0[0]}.{0[1]} {1}/{2}'.format(
    sys.version_info,
    __title__,
    __version__,
)

CRLF = '\r\n'


class BasicAuth(namedtuple('BasicAuth', ['login', 'password', 'encoding'])):
    """Http basic authentication helper."""

    def __new__(cls, login: str, password: str = '', encoding: str = 'latin1') -> 'BasicAuth':
        if login is None:
            raise ValueError('None is not allowed as login value')

        if password is None:
            raise ValueError('None is not allowed as password value')

        if ':' in login:
            raise ValueError('A ":" is not allowed in login (RFC 1945#section-11.1)')

        # noinspection PyTypeChecker,PyArgumentList
        return super().__new__(cls, login, password, encoding)

    @classmethod
    def decode(cls, auth_header: str, encoding: str = 'latin1') -> 'BasicAuth':
        """Create a BasicAuth object from an Authorization HTTP header."""
        try:
            auth_type, encoded_credentials = auth_header.split(' ', 1)
        except ValueError:
            raise ValueError('Could not parse authorization header.')

        if auth_type.lower() != 'basic':
            raise ValueError('Unknown authorization method %s' % auth_type)

        try:
            decoded = base64.b64decode(encoded_credentials.encode('ascii'), validate=True).decode(
                encoding
            )
        except binascii.Error:
            raise ValueError('Invalid base64 encoding.')

        try:
            # RFC 2617 HTTP Authentication
            # https://www.ietf.org/rfc/rfc2617.txt
            # the colon must be present, but the username and password may be
            # otherwise blank.
            username, password = decoded.split(':', 1)
        except ValueError:
            raise ValueError('Invalid credentials.')

        # noinspection PyTypeChecker
        return cls(username, password, encoding=encoding)

    def encode(self) -> str:
        """Encode credentials."""
        creds = ('%s:%s' % (self.login, self.password)).encode(self.encoding)
        return 'Basic %s' % base64.b64encode(creds).decode(self.encoding)


class _Buffer:
    def __init__(self, encoding: str = 'utf-8'):
        self._encoding = encoding
        self._buffer = bytearray()

    def append_line(self, line: str = ""):
        if line:
            self._buffer.extend(line.encode(self._encoding))

        self._buffer.extend(CRLF.encode('ascii'))

    def dumps(self) -> bytes:
        return bytes(self._buffer)


@dataclass
class ConnectRequest:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]

    def dumps(self) -> bytes:
        buff = _Buffer()
        buff.append_line(f'CONNECT {self.host}:{self.port} HTTP/1.1')
        buff.append_line(f'Host: {self.host}:{self.port}')
        buff.append_line(f'User-Agent: {DEFAULT_USER_AGENT}')

        if self.username and self.password:
            auth = BasicAuth(self.username, self.password)
            buff.append_line(f'Proxy-Authorization: {auth.encode()}')

        buff.append_line()

        return buff.dumps()


@dataclass
class ConnectReply:
    status_code: int
    message: str

    @classmethod
    def loads(cls, data: bytes) -> 'ConnectReply':
        if not data:
            raise ReplyError('Invalid proxy response')  # pragma: no cover

        line = data.split(CRLF.encode('ascii'), 1)[0]
        line = line.decode('utf-8', 'surrogateescape')

        try:
            version, code, *reason = line.split()
        except ValueError:  # pragma: no cover
            raise ReplyError(f'Invalid status line: {line}')

        try:
            status_code = int(code)
        except ValueError:  # pragma: no cover
            raise ReplyError(f'Invalid status code: {code}')

        status_message = " ".join(reason)

        if status_code != 200:
            msg = f'{status_code} {status_message}'
            raise ReplyError(msg, error_code=status_code)

        return cls(status_code=status_code, message=status_message)


# noinspection PyMethodMayBeStatic
class Connection:
    def send(self, request: ConnectRequest) -> bytes:
        return request.dumps()

    def receive(self, data: bytes) -> ConnectReply:
        return ConnectReply.loads(data)
