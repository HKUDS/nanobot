class SOCKSError(Exception):
    """Generic exception for when something goes wrong"""


class ProtocolError(SOCKSError):
    pass
