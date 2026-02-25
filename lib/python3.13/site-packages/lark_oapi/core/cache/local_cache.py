import time
from typing import Dict, Optional

from lark_oapi.core.cache import ICache


class LocalCache(ICache):

    def __init__(self):
        self.cache: Dict[str, LocalCache.ValueWrap] = {}

    def get(self, key: str) -> Optional[str]:
        wrap: LocalCache.ValueWrap = self.cache.get(key)
        if wrap is None:
            return None
        if wrap.expire < time.time():
            del self.cache[key]
            return None

        return wrap.value

    def set(self, key: str, value: str, expire: int) -> None:
        self.cache[key] = LocalCache.ValueWrap(value, expire)

    @staticmethod
    def instance() -> "LocalCache":
        if not hasattr(LocalCache, "__instance"):
            LocalCache.__instance = LocalCache()
        return LocalCache.__instance

    class ValueWrap(object):
        def __init__(self, value: str, expire: int):
            self.value = value
            self.expire = expire
