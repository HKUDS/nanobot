import enum
import functools
import re
import socket
import typing

from ._types import StrOrBytes

if typing.TYPE_CHECKING:
    from socksio.socks5 import SOCKS5AType  # pragma: nocover


IP_V6_WITH_PORT_REGEX = re.compile(r"^\[(?P<address>[^\]]+)\]:(?P<port>\d+)$")


class AddressType(enum.Enum):
    IPV4 = "IPV4"
    IPV6 = "IPV6"
    DN = "DN"

    @classmethod
    def from_socks5_atype(cls, socks5atype: "SOCKS5AType") -> "AddressType":
        from socksio.socks5 import SOCKS5AType

        if socks5atype == SOCKS5AType.IPV4_ADDRESS:
            return AddressType.IPV4
        elif socks5atype == SOCKS5AType.DOMAIN_NAME:
            return AddressType.DN
        elif socks5atype == SOCKS5AType.IPV6_ADDRESS:
            return AddressType.IPV6
        raise ValueError(socks5atype)


@functools.lru_cache(maxsize=64)
def encode_address(addr: StrOrBytes) -> typing.Tuple[AddressType, bytes]:
    """Determines the type of address and encodes it into the format SOCKS expects"""
    addr = addr.decode() if isinstance(addr, bytes) else addr
    try:
        return AddressType.IPV6, socket.inet_pton(socket.AF_INET6, addr)
    except OSError:
        try:
            return AddressType.IPV4, socket.inet_pton(socket.AF_INET, addr)
        except OSError:
            return AddressType.DN, addr.encode()


@functools.lru_cache(maxsize=64)
def decode_address(address_type: AddressType, encoded_addr: bytes) -> str:
    """Decodes the address from a SOCKS reply"""
    if address_type == AddressType.IPV6:
        return socket.inet_ntop(socket.AF_INET6, encoded_addr)
    elif address_type == AddressType.IPV4:
        return socket.inet_ntop(socket.AF_INET, encoded_addr)
    else:
        assert address_type == AddressType.DN
        return encoded_addr.decode()


def split_address_port_from_string(address: StrOrBytes) -> typing.Tuple[str, int]:
    """Returns a tuple (address: str, port: int) from an address string with a port
    i.e. '127.0.0.1:8080', '[0:0:0:0:0:0:0:1]:3080' or 'localhost:8080'.

    Note no validation is done on the domain or IP itself.
    """
    address = address.decode() if isinstance(address, bytes) else address
    match = re.match(IP_V6_WITH_PORT_REGEX, address)
    if match:
        address, str_port = match.group("address"), match.group("port")
    else:
        address, _, str_port = address.partition(":")

    try:
        return address, int(str_port)
    except ValueError:
        raise ValueError(
            "Invalid address + port. Please supply a valid domain name, IPV4 or IPV6 "
            "address with the port as a suffix, i.e. `127.0.0.1:3080`, "
            "`[0:0:0:0:0:0:0:1]:3080` or `localhost:3080`"
        ) from None


def get_address_port_tuple_from_address(
    address: typing.Union[StrOrBytes, typing.Tuple[StrOrBytes, int]]
) -> typing.Tuple[str, int]:
    """Returns an (address, port) from an address string-like or tuple."""
    if isinstance(address, tuple):
        address, port = address
        if isinstance(address, bytes):
            address = address.decode()
        if isinstance(port, (str, bytes)):
            port = int(port)
    else:
        address, port = split_address_port_from_string(address)

    return address, port
