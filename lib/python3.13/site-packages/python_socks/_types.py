from enum import Enum


class ProxyType(Enum):
    SOCKS4 = 1
    SOCKS5 = 2
    HTTP = 3
