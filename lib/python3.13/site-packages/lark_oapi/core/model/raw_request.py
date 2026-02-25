from typing import *


class RawRequest(object):
    def __init__(self):
        self.uri: Optional[str] = None
        self.headers: Dict[str, str] = {}
        self.body: Optional[bytes] = None
