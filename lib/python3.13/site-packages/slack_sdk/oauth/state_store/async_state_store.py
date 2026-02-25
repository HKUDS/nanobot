from logging import Logger


class AsyncOAuthStateStore:
    @property
    def logger(self) -> Logger:
        raise NotImplementedError()

    async def async_issue(self, *args, **kwargs) -> str:
        raise NotImplementedError()

    async def async_consume(self, state: str) -> bool:
        raise NotImplementedError()
