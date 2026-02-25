import inspect
import io
from collections.abc import Callable, Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    TypeVar,
)

import click
import click.shell_completion

if TYPE_CHECKING:  # pragma: no cover
    from .core import TyperCommand, TyperGroup
    from .main import Typer


NoneType = type(None)

AnyType = type[Any]

Required = ...


class Context(click.Context):
    """
    The [`Context`](https://click.palletsprojects.com/en/stable/api/#click.Context) has some additional data about the current execution of your program.
    When declaring it in a [callback](https://typer.tiangolo.com/tutorial/options/callback-and-context/) function,
    you can access this additional information.
    """

    pass


class FileText(io.TextIOWrapper):
    """
    Gives you a file-like object for reading text, and you will get a `str` data from it.
    The default mode of this class is `mode="r"`.

    **Example**

    ```python
    from typing import Annotated

    import typer

    app = typer.Typer()

    @app.command()
    def main(config: Annotated[typer.FileText, typer.Option()]):
        for line in config:
            print(f"Config line: {line}")

    if __name__ == "__main__":
        app()
    ```
    """

    pass


class FileTextWrite(FileText):
    """
    You can use this class for writing text. Alternatively, you can use `FileText` with `mode="w"`.
    The default mode of this class is `mode="w"`.

    **Example**

    ```python
    from typing import Annotated

    import typer

    app = typer.Typer()

    @app.command()
    def main(config: Annotated[typer.FileTextWrite, typer.Option()]):
        config.write("Some config written by the app")
        print("Config written")

    if __name__ == "__main__":
        app()
    ```
    """

    pass


class FileBinaryRead(io.BufferedReader):
    """
    You can use this class to read binary data, receiving `bytes`.
    The default mode of this class is `mode="rb"`.
    It is useful for reading binary files like images:

    **Example**

    ```python
    from typing import Annotated

    import typer

    app = typer.Typer()

    @app.command()
    def main(file: Annotated[typer.FileBinaryRead, typer.Option()]):
        processed_total = 0
        for bytes_chunk in file:
            # Process the bytes in bytes_chunk
            processed_total += len(bytes_chunk)
            print(f"Processed bytes total: {processed_total}")

    if __name__ == "__main__":
        app()
    ```
    """

    pass


class FileBinaryWrite(io.BufferedWriter):
    """
    You can use this class to write binary data: you pass `bytes` to it instead of strings.
    The default mode of this class is `mode="wb"`.
    It is useful for writing binary files like images:

    **Example**

    ```python
    from typing import Annotated

    import typer

    app = typer.Typer()

    @app.command()
    def main(file: Annotated[typer.FileBinaryWrite, typer.Option()]):
        first_line_str = "some settings\\n"
        # You cannot write str directly to a binary file; encode it first
        first_line_bytes = first_line_str.encode("utf-8")
        # Then you can write the bytes
        file.write(first_line_bytes)
        # This is already bytes, it starts with b"
        second_line = b"la cig\xc3\xbce\xc3\xb1a trae al ni\xc3\xb1o"
        file.write(second_line)
        print("Binary file written")

    if __name__ == "__main__":
        app()
    ```
    """

    pass


class CallbackParam(click.Parameter):
    """
    In a callback function, you can declare a function parameter with type `CallbackParam`
    to access the specific Click [`Parameter`](https://click.palletsprojects.com/en/stable/api/#click.Parameter) object.
    """

    pass


class DefaultPlaceholder:
    """
    You shouldn't use this class directly.

    It's used internally to recognize when a default value has been overwritten, even
    if the new value is `None`.
    """

    def __init__(self, value: Any):
        self.value = value

    def __bool__(self) -> bool:
        return bool(self.value)


DefaultType = TypeVar("DefaultType")

CommandFunctionType = TypeVar("CommandFunctionType", bound=Callable[..., Any])


def Default(value: DefaultType) -> DefaultType:
    """
    You shouldn't use this function directly.

    It's used internally to recognize when a default value has been overwritten, even
    if the new value is `None`.
    """
    return DefaultPlaceholder(value)  # type: ignore


class CommandInfo:
    def __init__(
        self,
        name: str | None = None,
        *,
        cls: type["TyperCommand"] | None = None,
        context_settings: dict[Any, Any] | None = None,
        callback: Callable[..., Any] | None = None,
        help: str | None = None,
        epilog: str | None = None,
        short_help: str | None = None,
        options_metavar: str = "[OPTIONS]",
        add_help_option: bool = True,
        no_args_is_help: bool = False,
        hidden: bool = False,
        deprecated: bool = False,
        # Rich settings
        rich_help_panel: str | None = None,
    ):
        self.name = name
        self.cls = cls
        self.context_settings = context_settings
        self.callback = callback
        self.help = help
        self.epilog = epilog
        self.short_help = short_help
        self.options_metavar = options_metavar
        self.add_help_option = add_help_option
        self.no_args_is_help = no_args_is_help
        self.hidden = hidden
        self.deprecated = deprecated
        # Rich settings
        self.rich_help_panel = rich_help_panel


class TyperInfo:
    def __init__(
        self,
        typer_instance: Optional["Typer"] = Default(None),
        *,
        name: str | None = Default(None),
        cls: type["TyperGroup"] | None = Default(None),
        invoke_without_command: bool = Default(False),
        no_args_is_help: bool = Default(False),
        subcommand_metavar: str | None = Default(None),
        chain: bool = Default(False),
        result_callback: Callable[..., Any] | None = Default(None),
        # Command
        context_settings: dict[Any, Any] | None = Default(None),
        callback: Callable[..., Any] | None = Default(None),
        help: str | None = Default(None),
        epilog: str | None = Default(None),
        short_help: str | None = Default(None),
        options_metavar: str = Default("[OPTIONS]"),
        add_help_option: bool = Default(True),
        hidden: bool = Default(False),
        deprecated: bool = Default(False),
        # Rich settings
        rich_help_panel: str | None = Default(None),
    ):
        self.typer_instance = typer_instance
        self.name = name
        self.cls = cls
        self.invoke_without_command = invoke_without_command
        self.no_args_is_help = no_args_is_help
        self.subcommand_metavar = subcommand_metavar
        self.chain = chain
        self.result_callback = result_callback
        self.context_settings = context_settings
        self.callback = callback
        self.help = help
        self.epilog = epilog
        self.short_help = short_help
        self.options_metavar = options_metavar
        self.add_help_option = add_help_option
        self.hidden = hidden
        self.deprecated = deprecated
        self.rich_help_panel = rich_help_panel


class ParameterInfo:
    def __init__(
        self,
        *,
        default: Any | None = None,
        param_decls: Sequence[str] | None = None,
        callback: Callable[..., Any] | None = None,
        metavar: str | None = None,
        expose_value: bool = True,
        is_eager: bool = False,
        envvar: str | list[str] | None = None,
        # Note that shell_complete is not fully supported and will be removed in future versions
        # TODO: Remove shell_complete in a future version (after 0.16.0)
        shell_complete: Callable[
            [click.Context, click.Parameter, str],
            list["click.shell_completion.CompletionItem"] | list[str],
        ]
        | None = None,
        autocompletion: Callable[..., Any] | None = None,
        default_factory: Callable[[], Any] | None = None,
        # Custom type
        parser: Callable[[str], Any] | None = None,
        click_type: click.ParamType | None = None,
        # TyperArgument
        show_default: bool | str = True,
        show_choices: bool = True,
        show_envvar: bool = True,
        help: str | None = None,
        hidden: bool = False,
        # Choice
        case_sensitive: bool = True,
        # Numbers
        min: int | float | None = None,
        max: int | float | None = None,
        clamp: bool = False,
        # DateTime
        formats: list[str] | None = None,
        # File
        mode: str | None = None,
        encoding: str | None = None,
        errors: str | None = "strict",
        lazy: bool | None = None,
        atomic: bool = False,
        # Path
        exists: bool = False,
        file_okay: bool = True,
        dir_okay: bool = True,
        writable: bool = False,
        readable: bool = True,
        resolve_path: bool = False,
        allow_dash: bool = False,
        path_type: None | type[str] | type[bytes] = None,
        # Rich settings
        rich_help_panel: str | None = None,
    ):
        # Check if user has provided multiple custom parsers
        if parser and click_type:
            raise ValueError(
                "Multiple custom type parsers provided. "
                "`parser` and `click_type` may not both be provided."
            )

        self.default = default
        self.param_decls = param_decls
        self.callback = callback
        self.metavar = metavar
        self.expose_value = expose_value
        self.is_eager = is_eager
        self.envvar = envvar
        self.shell_complete = shell_complete
        self.autocompletion = autocompletion
        self.default_factory = default_factory
        # Custom type
        self.parser = parser
        self.click_type = click_type
        # TyperArgument
        self.show_default = show_default
        self.show_choices = show_choices
        self.show_envvar = show_envvar
        self.help = help
        self.hidden = hidden
        # Choice
        self.case_sensitive = case_sensitive
        # Numbers
        self.min = min
        self.max = max
        self.clamp = clamp
        # DateTime
        self.formats = formats
        # File
        self.mode = mode
        self.encoding = encoding
        self.errors = errors
        self.lazy = lazy
        self.atomic = atomic
        # Path
        self.exists = exists
        self.file_okay = file_okay
        self.dir_okay = dir_okay
        self.writable = writable
        self.readable = readable
        self.resolve_path = resolve_path
        self.allow_dash = allow_dash
        self.path_type = path_type
        # Rich settings
        self.rich_help_panel = rich_help_panel


class OptionInfo(ParameterInfo):
    def __init__(
        self,
        *,
        # ParameterInfo
        default: Any | None = None,
        param_decls: Sequence[str] | None = None,
        callback: Callable[..., Any] | None = None,
        metavar: str | None = None,
        expose_value: bool = True,
        is_eager: bool = False,
        envvar: str | list[str] | None = None,
        # Note that shell_complete is not fully supported and will be removed in future versions
        # TODO: Remove shell_complete in a future version (after 0.16.0)
        shell_complete: Callable[
            [click.Context, click.Parameter, str],
            list["click.shell_completion.CompletionItem"] | list[str],
        ]
        | None = None,
        autocompletion: Callable[..., Any] | None = None,
        default_factory: Callable[[], Any] | None = None,
        # Custom type
        parser: Callable[[str], Any] | None = None,
        click_type: click.ParamType | None = None,
        # Option
        show_default: bool | str = True,
        prompt: bool | str = False,
        confirmation_prompt: bool = False,
        prompt_required: bool = True,
        hide_input: bool = False,
        # TODO: remove is_flag and flag_value in a future release
        is_flag: bool | None = None,
        flag_value: Any | None = None,
        count: bool = False,
        allow_from_autoenv: bool = True,
        help: str | None = None,
        hidden: bool = False,
        show_choices: bool = True,
        show_envvar: bool = True,
        # Choice
        case_sensitive: bool = True,
        # Numbers
        min: int | float | None = None,
        max: int | float | None = None,
        clamp: bool = False,
        # DateTime
        formats: list[str] | None = None,
        # File
        mode: str | None = None,
        encoding: str | None = None,
        errors: str | None = "strict",
        lazy: bool | None = None,
        atomic: bool = False,
        # Path
        exists: bool = False,
        file_okay: bool = True,
        dir_okay: bool = True,
        writable: bool = False,
        readable: bool = True,
        resolve_path: bool = False,
        allow_dash: bool = False,
        path_type: None | type[str] | type[bytes] = None,
        # Rich settings
        rich_help_panel: str | None = None,
    ):
        super().__init__(
            default=default,
            param_decls=param_decls,
            callback=callback,
            metavar=metavar,
            expose_value=expose_value,
            is_eager=is_eager,
            envvar=envvar,
            shell_complete=shell_complete,
            autocompletion=autocompletion,
            default_factory=default_factory,
            # Custom type
            parser=parser,
            click_type=click_type,
            # TyperArgument
            show_default=show_default,
            show_choices=show_choices,
            show_envvar=show_envvar,
            help=help,
            hidden=hidden,
            # Choice
            case_sensitive=case_sensitive,
            # Numbers
            min=min,
            max=max,
            clamp=clamp,
            # DateTime
            formats=formats,
            # File
            mode=mode,
            encoding=encoding,
            errors=errors,
            lazy=lazy,
            atomic=atomic,
            # Path
            exists=exists,
            file_okay=file_okay,
            dir_okay=dir_okay,
            writable=writable,
            readable=readable,
            resolve_path=resolve_path,
            allow_dash=allow_dash,
            path_type=path_type,
            # Rich settings
            rich_help_panel=rich_help_panel,
        )
        if is_flag is not None or flag_value is not None:
            import warnings

            warnings.warn(
                "The 'is_flag' and 'flag_value' parameters are not supported by Typer "
                "and will be removed entirely in a future release.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.prompt = prompt
        self.confirmation_prompt = confirmation_prompt
        self.prompt_required = prompt_required
        self.hide_input = hide_input
        self.count = count
        self.allow_from_autoenv = allow_from_autoenv


class ArgumentInfo(ParameterInfo):
    def __init__(
        self,
        *,
        # ParameterInfo
        default: Any | None = None,
        param_decls: Sequence[str] | None = None,
        callback: Callable[..., Any] | None = None,
        metavar: str | None = None,
        expose_value: bool = True,
        is_eager: bool = False,
        envvar: str | list[str] | None = None,
        # Note that shell_complete is not fully supported and will be removed in future versions
        # TODO: Remove shell_complete in a future version (after 0.16.0)
        shell_complete: Callable[
            [click.Context, click.Parameter, str],
            list["click.shell_completion.CompletionItem"] | list[str],
        ]
        | None = None,
        autocompletion: Callable[..., Any] | None = None,
        default_factory: Callable[[], Any] | None = None,
        # Custom type
        parser: Callable[[str], Any] | None = None,
        click_type: click.ParamType | None = None,
        # TyperArgument
        show_default: bool | str = True,
        show_choices: bool = True,
        show_envvar: bool = True,
        help: str | None = None,
        hidden: bool = False,
        # Choice
        case_sensitive: bool = True,
        # Numbers
        min: int | float | None = None,
        max: int | float | None = None,
        clamp: bool = False,
        # DateTime
        formats: list[str] | None = None,
        # File
        mode: str | None = None,
        encoding: str | None = None,
        errors: str | None = "strict",
        lazy: bool | None = None,
        atomic: bool = False,
        # Path
        exists: bool = False,
        file_okay: bool = True,
        dir_okay: bool = True,
        writable: bool = False,
        readable: bool = True,
        resolve_path: bool = False,
        allow_dash: bool = False,
        path_type: None | type[str] | type[bytes] = None,
        # Rich settings
        rich_help_panel: str | None = None,
    ):
        super().__init__(
            default=default,
            param_decls=param_decls,
            callback=callback,
            metavar=metavar,
            expose_value=expose_value,
            is_eager=is_eager,
            envvar=envvar,
            shell_complete=shell_complete,
            autocompletion=autocompletion,
            default_factory=default_factory,
            # Custom type
            parser=parser,
            click_type=click_type,
            # TyperArgument
            show_default=show_default,
            show_choices=show_choices,
            show_envvar=show_envvar,
            help=help,
            hidden=hidden,
            # Choice
            case_sensitive=case_sensitive,
            # Numbers
            min=min,
            max=max,
            clamp=clamp,
            # DateTime
            formats=formats,
            # File
            mode=mode,
            encoding=encoding,
            errors=errors,
            lazy=lazy,
            atomic=atomic,
            # Path
            exists=exists,
            file_okay=file_okay,
            dir_okay=dir_okay,
            writable=writable,
            readable=readable,
            resolve_path=resolve_path,
            allow_dash=allow_dash,
            path_type=path_type,
            # Rich settings
            rich_help_panel=rich_help_panel,
        )


class ParamMeta:
    empty = inspect.Parameter.empty

    def __init__(
        self,
        *,
        name: str,
        default: Any = inspect.Parameter.empty,
        annotation: Any = inspect.Parameter.empty,
    ) -> None:
        self.name = name
        self.default = default
        self.annotation = annotation


class DeveloperExceptionConfig:
    def __init__(
        self,
        *,
        pretty_exceptions_enable: bool = True,
        pretty_exceptions_show_locals: bool = True,
        pretty_exceptions_short: bool = True,
    ) -> None:
        self.pretty_exceptions_enable = pretty_exceptions_enable
        self.pretty_exceptions_show_locals = pretty_exceptions_show_locals
        self.pretty_exceptions_short = pretty_exceptions_short


class TyperPath(click.Path):
    # Overwrite Click's behaviour to be compatible with Typer's autocompletion system
    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[click.shell_completion.CompletionItem]:
        """Return an empty list so that the autocompletion functionality
        will work properly from the commandline.
        """
        return []
