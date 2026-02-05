import sys
from asyncio import AbstractEventLoop
from datetime import datetime, time, timedelta
from logging import Handler
from multiprocessing.context import BaseContext
from types import TracebackType
from typing import (
    Any,
    BinaryIO,
    Callable,
    Dict,
    Generator,
    Generic,
    List,
    NamedTuple,
    NewType,
    Optional,
    Pattern,
    Sequence,
    TextIO,
    Tuple,
    Type,
    TypeVar,
    Union,
    overload,
)

if sys.version_info >= (3, 6):
    from typing import Awaitable
else:
    from typing_extensions import Awaitable

if sys.version_info >= (3, 6):
    from os import PathLike
    from typing import ContextManager

    PathLikeStr = PathLike[str]
else:
    from pathlib import PurePath as PathLikeStr

    from typing_extensions import ContextManager

if sys.version_info >= (3, 8):
    from typing import Protocol, TypedDict
else:
    from typing_extensions import Protocol, TypedDict

_T = TypeVar("_T")
_F = TypeVar("_F", bound=Callable[..., Any])
ExcInfo = Tuple[Optional[Type[BaseException]], Optional[BaseException], Optional[TracebackType]]

class _GeneratorContextManager(ContextManager[_T], Generic[_T]):
    def __call__(self, func: _F) -> _F: ...
    def __exit__(
        self,
        typ: Optional[Type[BaseException]],
        value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Optional[bool]: ...

Catcher = NewType("Catcher", _GeneratorContextManager[None])
Contextualizer = NewType("Contextualizer", _GeneratorContextManager[None])
AwaitableCompleter = Awaitable[None]

class Level(NamedTuple):
    name: str
    no: int
    color: str
    icon: str

class _RecordAttribute:
    def __format__(self, spec: str) -> str: ...

class RecordFile(_RecordAttribute):
    name: str
    path: str

class RecordLevel(_RecordAttribute):
    name: str
    no: int
    icon: str

class RecordThread(_RecordAttribute):
    id: int
    name: str

class RecordProcess(_RecordAttribute):
    id: int
    name: str

class RecordException(NamedTuple):
    type: Optional[Type[BaseException]]
    value: Optional[BaseException]
    traceback: Optional[TracebackType]

class Record(TypedDict):
    elapsed: timedelta
    exception: Optional[RecordException]
    extra: Dict[Any, Any]
    file: RecordFile
    function: str
    level: RecordLevel
    line: int
    message: str
    module: str
    name: Optional[str]
    process: RecordProcess
    thread: RecordThread
    time: datetime

class Message(str):
    record: Record

class Writable(Protocol):
    def write(self, message: Message) -> None: ...

FilterDict = Dict[Optional[str], Union[str, int, bool]]
FilterFunction = Callable[[Record], bool]
FormatFunction = Callable[[Record], str]
PatcherFunction = Callable[[Record], None]
RotationFunction = Callable[[Message, TextIO], bool]
RetentionFunction = Callable[[List[str]], None]
CompressionFunction = Callable[[str], None]

StandardOpener = Callable[[str, int], int]

class BasicHandlerConfig(TypedDict, total=False):
    sink: Union[TextIO, Writable, Callable[[Message], None], Handler]
    level: Union[str, int]
    format: Union[str, FormatFunction]
    filter: Optional[Union[str, FilterFunction, FilterDict]]
    colorize: Optional[bool]
    serialize: bool
    backtrace: bool
    diagnose: bool
    enqueue: bool
    catch: bool

class FileHandlerConfig(TypedDict, total=False):
    sink: Union[str, PathLikeStr]
    level: Union[str, int]
    format: Union[str, FormatFunction]
    filter: Optional[Union[str, FilterFunction, FilterDict]]
    colorize: Optional[bool]
    serialize: bool
    backtrace: bool
    diagnose: bool
    enqueue: bool
    catch: bool
    rotation: Optional[Union[str, int, time, timedelta, RotationFunction]]
    retention: Optional[Union[str, int, timedelta, RetentionFunction]]
    compression: Optional[Union[str, CompressionFunction]]
    delay: bool
    watch: bool
    mode: str
    buffering: int
    encoding: str
    errors: Optional[str]
    newline: Optional[str]
    closefd: bool
    opener: Optional[StandardOpener]

class AsyncHandlerConfig(TypedDict, total=False):
    sink: Callable[[Message], Awaitable[None]]
    level: Union[str, int]
    format: Union[str, FormatFunction]
    filter: Optional[Union[str, FilterFunction, FilterDict]]
    colorize: Optional[bool]
    serialize: bool
    backtrace: bool
    diagnose: bool
    enqueue: bool
    catch: bool
    context: Optional[Union[str, BaseContext]]
    loop: Optional[AbstractEventLoop]

HandlerConfig = Union[BasicHandlerConfig, FileHandlerConfig, AsyncHandlerConfig]

class LevelConfig(TypedDict, total=False):
    name: str
    no: int
    color: str
    icon: str

ActivationConfig = Tuple[Optional[str], bool]

class Logger:
    @overload
    def add(
        self,
        sink: Union[TextIO, Writable, Callable[[Message], None], Handler],
        *,
        level: Union[str, int] = ...,
        format: Union[str, FormatFunction] = ...,
        filter: Optional[Union[str, FilterFunction, FilterDict]] = ...,
        colorize: Optional[bool] = ...,
        serialize: bool = ...,
        backtrace: bool = ...,
        diagnose: bool = ...,
        enqueue: bool = ...,
        context: Optional[Union[str, BaseContext]] = ...,
        catch: bool = ...
    ) -> int: ...
    @overload
    def add(
        self,
        sink: Callable[[Message], Awaitable[None]],
        *,
        level: Union[str, int] = ...,
        format: Union[str, FormatFunction] = ...,
        filter: Optional[Union[str, FilterFunction, FilterDict]] = ...,
        colorize: Optional[bool] = ...,
        serialize: bool = ...,
        backtrace: bool = ...,
        diagnose: bool = ...,
        enqueue: bool = ...,
        catch: bool = ...,
        context: Optional[Union[str, BaseContext]] = ...,
        loop: Optional[AbstractEventLoop] = ...
    ) -> int: ...
    @overload
    def add(
        self,
        sink: Union[str, PathLikeStr],
        *,
        level: Union[str, int] = ...,
        format: Union[str, FormatFunction] = ...,
        filter: Optional[Union[str, FilterFunction, FilterDict]] = ...,
        colorize: Optional[bool] = ...,
        serialize: bool = ...,
        backtrace: bool = ...,
        diagnose: bool = ...,
        enqueue: bool = ...,
        context: Optional[Union[str, BaseContext]] = ...,
        catch: bool = ...,
        rotation: Optional[Union[str, int, time, timedelta, RotationFunction]] = ...,
        retention: Optional[Union[str, int, timedelta, RetentionFunction]] = ...,
        compression: Optional[Union[str, CompressionFunction]] = ...,
        delay: bool = ...,
        watch: bool = ...,
        mode: str = ...,
        buffering: int = ...,
        encoding: str = ...,
        errors: Optional[str] = ...,
        newline: Optional[str] = ...,
        closefd: bool = ...,
        opener: Optional[StandardOpener] = ...,
    ) -> int: ...
    def remove(self, handler_id: Optional[int] = ...) -> None: ...
    def complete(self) -> AwaitableCompleter: ...
    @overload
    def catch(
        self,
        exception: Union[Type[BaseException], Tuple[Type[BaseException], ...]] = ...,
        *,
        level: Union[str, int] = ...,
        reraise: bool = ...,
        onerror: Optional[Callable[[BaseException], None]] = ...,
        exclude: Optional[Union[Type[BaseException], Tuple[Type[BaseException], ...]]] = ...,
        default: Any = ...,
        message: str = ...
    ) -> Catcher: ...
    @overload
    def catch(self, function: _F) -> _F: ...
    def opt(
        self,
        *,
        exception: Optional[Union[bool, ExcInfo, BaseException]] = ...,
        record: bool = ...,
        lazy: bool = ...,
        colors: bool = ...,
        raw: bool = ...,
        capture: bool = ...,
        depth: int = ...,
        ansi: bool = ...
    ) -> Logger: ...
    def bind(__self, **kwargs: Any) -> Logger: ...  # noqa: N805
    def contextualize(__self, **kwargs: Any) -> Contextualizer: ...  # noqa: N805
    def patch(self, patcher: PatcherFunction) -> Logger: ...
    @overload
    def level(self, name: str) -> Level: ...
    @overload
    def level(
        self, name: str, no: int = ..., color: Optional[str] = ..., icon: Optional[str] = ...
    ) -> Level: ...
    @overload
    def level(
        self,
        name: str,
        no: Optional[int] = ...,
        color: Optional[str] = ...,
        icon: Optional[str] = ...,
    ) -> Level: ...
    def disable(self, name: Optional[str]) -> None: ...
    def enable(self, name: Optional[str]) -> None: ...
    def configure(
        self,
        *,
        handlers: Optional[Sequence[HandlerConfig]] = ...,
        levels: Optional[Sequence[LevelConfig]] = ...,
        extra: Optional[Dict[Any, Any]] = ...,
        patcher: Optional[PatcherFunction] = ...,
        activation: Optional[Sequence[ActivationConfig]] = ...
    ) -> List[int]: ...
    # @staticmethod cannot be used with @overload in mypy (python/mypy#7781).
    # However Logger is not exposed and logger is an instance of Logger
    # so for type checkers it is all the same whether it is defined here
    # as a static method or an instance method.
    @overload
    def parse(
        self,
        file: Union[str, PathLikeStr, TextIO],
        pattern: Union[str, Pattern[str]],
        *,
        cast: Union[Dict[str, Callable[[str], Any]], Callable[[Dict[str, str]], None]] = ...,
        chunk: int = ...
    ) -> Generator[Dict[str, Any], None, None]: ...
    @overload
    def parse(
        self,
        file: BinaryIO,
        pattern: Union[bytes, Pattern[bytes]],
        *,
        cast: Union[Dict[str, Callable[[bytes], Any]], Callable[[Dict[str, bytes]], None]] = ...,
        chunk: int = ...
    ) -> Generator[Dict[str, Any], None, None]: ...
    @overload
    def trace(__self, __message: str, *args: Any, **kwargs: Any) -> None: ...  # noqa: N805
    @overload
    def trace(__self, __message: Any) -> None: ...  # noqa: N805
    @overload
    def debug(__self, __message: str, *args: Any, **kwargs: Any) -> None: ...  # noqa: N805
    @overload
    def debug(__self, __message: Any) -> None: ...  # noqa: N805
    @overload
    def info(__self, __message: str, *args: Any, **kwargs: Any) -> None: ...  # noqa: N805
    @overload
    def info(__self, __message: Any) -> None: ...  # noqa: N805
    @overload
    def success(__self, __message: str, *args: Any, **kwargs: Any) -> None: ...  # noqa: N805
    @overload
    def success(__self, __message: Any) -> None: ...  # noqa: N805
    @overload
    def warning(__self, __message: str, *args: Any, **kwargs: Any) -> None: ...  # noqa: N805
    @overload
    def warning(__self, __message: Any) -> None: ...  # noqa: N805
    @overload
    def error(__self, __message: str, *args: Any, **kwargs: Any) -> None: ...  # noqa: N805
    @overload
    def error(__self, __message: Any) -> None: ...  # noqa: N805
    @overload
    def critical(__self, __message: str, *args: Any, **kwargs: Any) -> None: ...  # noqa: N805
    @overload
    def critical(__self, __message: Any) -> None: ...  # noqa: N805
    @overload
    def exception(__self, __message: str, *args: Any, **kwargs: Any) -> None: ...  # noqa: N805
    @overload
    def exception(__self, __message: Any) -> None: ...  # noqa: N805
    @overload
    def log(
        __self, __level: Union[int, str], __message: str, *args: Any, **kwargs: Any  # noqa: N805
    ) -> None: ...
    @overload
    def log(__self, __level: Union[int, str], __message: Any) -> None: ...  # noqa: N805
    def start(self, *args: Any, **kwargs: Any) -> int: ...
    def stop(self, *args: Any, **kwargs: Any) -> None: ...

logger: Logger
