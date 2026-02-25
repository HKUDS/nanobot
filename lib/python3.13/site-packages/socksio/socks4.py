import enum
import typing

from ._types import StrOrBytes
from .exceptions import ProtocolError, SOCKSError
from .utils import (
    AddressType,
    decode_address,
    encode_address,
    get_address_port_tuple_from_address,
)


class SOCKS4ReplyCode(bytes, enum.Enum):
    """Enumeration of SOCKS4 reply codes."""

    REQUEST_GRANTED = b"\x5A"
    REQUEST_REJECTED_OR_FAILED = b"\x5B"
    CONNECTION_FAILED = b"\x5C"
    AUTHENTICATION_FAILED = b"\x5D"


class SOCKS4Command(bytes, enum.Enum):
    """Enumeration of SOCKS4 command codes."""

    CONNECT = b"\x01"
    BIND = b"\x02"


class SOCKS4Request(typing.NamedTuple):
    """Encapsulates a request to the SOCKS4 proxy server

    Args:
        command: The command to request.
        port: The port number to connect to on the target host.
        addr: IP address of the target host.
        user_id: Optional user ID to be included in the request, if not supplied
            the user *must* provide one in the packing operation.
    """

    command: SOCKS4Command
    port: int
    addr: bytes
    user_id: typing.Optional[bytes] = None

    @classmethod
    def from_address(
        cls,
        command: SOCKS4Command,
        address: typing.Union[StrOrBytes, typing.Tuple[StrOrBytes, int]],
        user_id: typing.Optional[bytes] = None,
    ) -> "SOCKS4Request":
        """Convenience class method to build an instance from command and address.

        Args:
            command: The command to request.
            address: A string in the form 'HOST:PORT' or a tuple of ip address string
                and port number.
            user_id: Optional user ID.

        Returns:
            A SOCKS4Request instance.

        Raises:
            SOCKSError: If a domain name or IPv6 address was supplied.
        """
        address, port = get_address_port_tuple_from_address(address)
        atype, encoded_addr = encode_address(address)
        if atype != AddressType.IPV4:
            raise SOCKSError(
                "IPv6 addresses and domain names are not supported by SOCKS4"
            )
        return cls(command=command, addr=encoded_addr, port=port, user_id=user_id)

    def dumps(self, user_id: typing.Optional[bytes] = None) -> bytes:
        """Packs the instance into a raw binary in the appropriate form.

        Args:
            user_id: Optional user ID as an override, if not provided the instance's
                will be used, if none was provided at initialization an error is raised.

        Returns:
            The packed request.

        Raises:
            SOCKSError: If no user was specified in this call or on initialization.
        """
        user_id = user_id or self.user_id
        if user_id is None:
            raise SOCKSError("SOCKS4 requires a user_id, none was specified")

        return b"".join(
            [
                b"\x04",
                self.command,
                (self.port).to_bytes(2, byteorder="big"),
                self.addr,
                user_id,
                b"\x00",
            ]
        )


class SOCKS4ARequest(typing.NamedTuple):
    """Encapsulates a request to the SOCKS4A proxy server

    Args:
        command: The command to request.
        port: The port number to connect to on the target host.
        addr: IP address of the target host.
        user_id: Optional user ID to be included in the request, if not supplied
            the user *must* provide one in the packing operation.
    """

    command: SOCKS4Command
    port: int
    addr: bytes
    user_id: typing.Optional[bytes] = None

    @classmethod
    def from_address(
        cls,
        command: SOCKS4Command,
        address: typing.Union[StrOrBytes, typing.Tuple[StrOrBytes, int]],
        user_id: typing.Optional[bytes] = None,
    ) -> "SOCKS4ARequest":
        """Convenience class method to build an instance from command and address.

        Args:
            command: The command to request.
            address: A string in the form 'HOST:PORT' or a tuple of ip address string
                and port number.
            user_id: Optional user ID.

        Returns:
            A SOCKS4ARequest instance.
        """
        address, port = get_address_port_tuple_from_address(address)
        atype, encoded_addr = encode_address(address)
        return cls(command=command, addr=encoded_addr, port=port, user_id=user_id)

    def dumps(self, user_id: typing.Optional[bytes] = None) -> bytes:
        """Packs the instance into a raw binary in the appropriate form.

        Args:
            user_id: Optional user ID as an override, if not provided the instance's
                will be used, if none was provided at initialization an error is raised.

        Returns:
            The packed request.

        Raises:
            SOCKSError: If no user was specified in this call or on initialization.
        """
        user_id = user_id or self.user_id
        if user_id is None:
            raise SOCKSError("SOCKS4 requires a user_id, none was specified")

        return b"".join(
            [
                b"\x04",
                self.command,
                (self.port).to_bytes(2, byteorder="big"),
                b"\x00\x00\x00\xFF",  # arbitrary final non-zero byte
                user_id,
                b"\x00",
                self.addr,
                b"\x00",
            ]
        )


class SOCKS4Reply(typing.NamedTuple):
    """Encapsulates a reply from the SOCKS4 proxy server

    Args:
        reply_code: The code representing the type of reply.
        port: The port number returned.
        addr: Optional IP address returned.
    """

    reply_code: SOCKS4ReplyCode
    port: int
    addr: typing.Optional[str]

    @classmethod
    def loads(cls, data: bytes) -> "SOCKS4Reply":
        """Unpacks the reply data into an instance.

        Returns:
            The unpacked reply instance.

        Raises:
            ProtocolError: If the data does not match the spec.
        """
        if len(data) != 8 or data[0:1] != b"\x00":
            raise ProtocolError("Malformed reply")

        try:
            return cls(
                reply_code=SOCKS4ReplyCode(data[1:2]),
                port=int.from_bytes(data[2:4], byteorder="big"),
                addr=decode_address(AddressType.IPV4, data[4:8]),
            )
        except ValueError as exc:
            raise ProtocolError("Malformed reply") from exc


class SOCKS4Connection:
    """Encapsulates a SOCKS4 and SOCKS4A connection.

    Packs request objects into data suitable to be send and unpacks reply
    data into their appropriate reply objects.

    Args:
        user_id: The user ID to be sent as part of the requests.
    """

    def __init__(self, user_id: bytes):
        self.user_id = user_id

        self._data_to_send = bytearray()
        self._received_data = bytearray()

    def send(self, request: typing.Union[SOCKS4Request, SOCKS4ARequest]) -> None:
        """Packs a request object and adds it to the send data buffer.

        Args:
            request: The request instance to be packed.
        """
        user_id = request.user_id or self.user_id
        self._data_to_send += request.dumps(user_id=user_id)

    def receive_data(self, data: bytes) -> SOCKS4Reply:
        """Unpacks response data into a reply object.

        Args:
            data: The raw response data from the proxy server.

        Returns:
            The appropriate reply object.
        """
        self._received_data += data
        return SOCKS4Reply.loads(bytes(self._received_data))

    def data_to_send(self) -> bytes:
        """Returns the data to be sent via the I/O library of choice.

        Also clears the connection's buffer.
        """
        data = bytes(self._data_to_send)
        self._data_to_send = bytearray()
        return data
