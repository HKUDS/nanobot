from abc import ABC, abstractmethod
from typing import *

from lark_oapi.core import T


class IEventProcessor(ABC, Generic[T]):
    @abstractmethod
    def type(self) -> Type[T]:
        pass

    @abstractmethod
    def do(self, data: T) -> None:
        pass


class ICallBackProcessor(ABC, Generic[T]):
    @abstractmethod
    def type(self) -> Type[T]:
        pass

    @abstractmethod
    def do(self, data: T) -> Any:
        pass
