from enum import Enum, auto


class ContextValues(Enum):
    OBJECT_KEY = auto()
    OBJECT_VALUE = auto()
    ARRAY = auto()


class JsonContext:
    def __init__(self) -> None:
        self.context: list[ContextValues] = []
        self.current: ContextValues | None = None
        self.empty: bool = True

    def set(self, value: ContextValues) -> None:
        """
        Set a new context value.

        Args:
            value (ContextValues): The context value to be added.

        Returns:
            None
        """
        self.context.append(value)
        self.current = value
        self.empty = False

    def reset(self) -> None:
        """
        Remove the most recent context value.

        Returns:
            None
        """
        try:
            self.context.pop()
            self.current = self.context[-1]
        except IndexError:
            self.current = None
            self.empty = True
