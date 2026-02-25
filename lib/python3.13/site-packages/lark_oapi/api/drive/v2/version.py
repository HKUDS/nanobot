from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.file_like: FileLike = FileLike(config)
        self.permission_public: PermissionPublic = PermissionPublic(config)
