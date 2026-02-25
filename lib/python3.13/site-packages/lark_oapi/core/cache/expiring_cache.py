import asyncio
import time
from typing import Dict, Tuple, Any


class ExpiringCache(object):

    def __init__(self, clear_interval=60):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._clear_interval: int = clear_interval

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self._cron = loop.create_task(self._start_clear_cron())

    def __del__(self):
        self._cron.cancel()

    def get(self, key: str) -> Any:
        elem = self._cache.get(key)
        if not elem:
            return None
        value, expire = elem
        if expire < time.time():
            del self._cache[key]
            return None

        return value

    # ttl: 存活时间，单位秒
    def set(self, key: str, value: Any, ttl: int):
        expire = time.time() + ttl
        self._cache[key] = (value, expire)

    def _clear(self):
        now = time.time()
        expired_keys = [key for key, (value, expire) in self._cache.items() if expire < now]
        for key in expired_keys:
            del self._cache[key]

    async def _start_clear_cron(self):
        while True:
            await asyncio.sleep(self._clear_interval)
            self._clear()
