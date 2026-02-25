from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.moto: Moto = Moto(config)
