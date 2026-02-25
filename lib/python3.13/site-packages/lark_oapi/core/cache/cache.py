from abc import ABC, abstractmethod


class ICache(ABC):
    @abstractmethod
    def get(self, key: str) -> str:
        pass

    # expire: 过期时间, Unix时间戳（秒）
    @abstractmethod
    def set(self, key: str, value: str, expire: int):
        pass
