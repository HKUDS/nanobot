from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any, overload

import click
from annotated_doc import Doc

from .models import ArgumentInfo, OptionInfo

if TYPE_CHECKING:  # pragma: no cover
    import click.shell_completion


# Overload for Option created with custom type 'parser'
@overload
def Option(
    # Parameter
    default: Any | None = ...,
    *param_decls: str,
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
) -> Any: ...


# Overload for Option created with custom type 'click_type'
@overload
def Option(
    # Parameter
    default: Any | None = ...,
    *param_decls: str,
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
) -> Any: ...


def Option(
    # Parameter
    default: Annotated[
        Any | None,
        Doc(
            """
            Usually, [CLI options](https://typer.tiangolo.com/tutorial/options/) are optional and have a default value, passed on like this:

            **Example**

            ```python
            @app.command()
            def main(network: str = typer.Option("CNN")):
                print(f"Training neural network of type: {network}")
            ```

            Note that this usage is deprecated, and we recommend to use `Annotated` instead:
            ```
            @app.command()
            def main(network: Annotated[str, typer.Option()] = "CNN"):
                print(f"Hello {name}!")
            ```

            You can also use `...` ([Ellipsis](https://docs.python.org/3/library/constants.html#Ellipsis)) as the "default" value to clarify that this is a required CLI option.
            """
        ),
    ] = ...,
    *param_decls: Annotated[
        str,
        Doc(
            """
            Positional argument that defines how users can call this option on the command line. This may be one or multiple aliases, all strings.
            If not defined, Typer will automatically use the function parameter as default name.
            See [the tutorial about CLI Option Names](https://typer.tiangolo.com/tutorial/options/name/) for more details.

            **Example**

            ```python
            @app.command()
            def main(user_name: Annotated[str, typer.Option("--user", "-u", "-x")]):
                print(f"Hello {user_name}")
            ```
            """
        ),
    ],
    callback: Annotated[
        Callable[..., Any] | None,
        Doc(
            """
            Add a callback to this CLI Option, to execute additional logic after its value was received from the terminal.
            See [the tutorial about callbacks](https://typer.tiangolo.com/tutorial/options/callback-and-context/) for more details.

            **Example**

            ```python
            def name_callback(value: str):
                if value != "Deadpool":
                    raise typer.BadParameter("Only Deadpool is allowed")
                return value

            @app.command()
            def main(name: Annotated[str, typer.Option(callback=name_callback)]):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = None,
    metavar: Annotated[
        str | None,
        Doc(
            """
            Customize the name displayed in the [help text](https://typer.tiangolo.com/tutorial/options/help/) to represent this CLI option.
            Note that this doesn't influence the way the option must be called.

            **Example**

            ```python
            @app.command()
            def main(user: Annotated[str, typer.Option(metavar="User name")]):
                print(f"Hello {user}")
            ```
            """
        ),
    ] = None,
    expose_value: Annotated[
        bool,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.

            ---

            If this is `True` then the value is passed onwards to the command callback and stored on the context, otherwise it’s skipped.
            """
        ),
    ] = True,
    is_eager: Annotated[
        bool,
        Doc(
            """
            Mark a CLI Option to be "eager", ensuring it gets processed before other CLI parameters. This could be relevant when there are other parameters with callbacks that could exit the program early.
            For more information and an extended example, see the documentation [here](https://typer.tiangolo.com/tutorial/options/version/#fix-with-is_eager).
            """
        ),
    ] = False,
    envvar: Annotated[
        str | list[str] | None,
        Doc(
            """
            Configure a CLI Option to read its value from an environment variable if it is not provided in the command line.
            For more information, see the [documentation on Environment Variables](https://typer.tiangolo.com/tutorial/arguments/envvar/).

            **Example**

            ```python
            @app.command()
            def main(user: Annotated[str, typer.Option(envvar="ME")]):
                print(f"Hello {user}")
            ```
            """
        ),
    ] = None,
    # TODO: Remove shell_complete in a future version (after 0.16.0)
    shell_complete: Annotated[
        Callable[
            [click.Context, click.Parameter, str],
            list["click.shell_completion.CompletionItem"] | list[str],
        ]
        | None,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.
            It is however not fully functional, and will likely be removed in future versions.
            """
        ),
    ] = None,
    autocompletion: Annotated[
        Callable[..., Any] | None,
        Doc(
            """
            Provide a custom function that helps to autocomplete the values of this CLI Option.
            See [the tutorial on parameter autocompletion](https://typer.tiangolo.com/tutorial/options-autocompletion) for more details.

            **Example**

            ```python
            def complete():
                return ["Me", "Myself", "I"]

            @app.command()
            def main(name: Annotated[str, typer.Option(autocompletion=complete)]):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = None,
    default_factory: Annotated[
        Callable[[], Any] | None,
        Doc(
            """
            Provide a custom function that dynamically generates a [default](https://typer.tiangolo.com/tutorial/arguments/default) for this CLI Option.

            **Example**

            ```python
            def get_name():
                return random.choice(["Me", "Myself", "I"])

            @app.command()
            def main(name: Annotated[str, typer.Option(default_factory=get_name)]):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = None,
    # Custom type
    parser: Annotated[
        Callable[[str], Any] | None,
        Doc(
            """
            Use your own custom types in Typer applications by defining a `parser` function that parses input into your own types:

            **Example**

            ```python
            class CustomClass:
                def __init__(self, value: str):
                    self.value = value

                def __str__(self):
                    return f"<CustomClass: value={self.value}>"

            def my_parser(value: str):
                return CustomClass(value * 2)

            @app.command()
            def main(opt: Annotated[CustomClass, typer.Option(parser=my_parser)] = "Foo"):
                print(f"--opt is {opt}")
            ```
            """
        ),
    ] = None,
    click_type: Annotated[
        click.ParamType | None,
        Doc(
            """
            Define this parameter to use a [custom Click type](https://click.palletsprojects.com/en/stable/parameters/#implementing-custom-types) in your Typer applications.

            **Example**

            ```python
            class MyClass:
                def __init__(self, value: str):
                    self.value = value

                def __str__(self):
                    return f"<MyClass: value={self.value}>"

            class MyParser(click.ParamType):
                name = "MyClass"

                def convert(self, value, param, ctx):
                    return MyClass(value * 3)

            @app.command()
            def main(opt: Annotated[MyClass, typer.Option(click_type=MyParser())] = "Foo"):
                print(f"--opt is {opt}")
            ```
            """
        ),
    ] = None,
    # Option
    show_default: Annotated[
        bool | str,
        Doc(
            """
            When set to `False`, don't show the default value of this CLI Option in the [help text](https://typer.tiangolo.com/tutorial/options/help/).

            **Example**

            ```python
            @app.command()
            def main(name: Annotated[str, typer.Option(show_default=False)] = "Rick"):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = True,
    prompt: Annotated[
        bool | str,
        Doc(
            """
            When set to `True`, a prompt will appear to ask for the value of this CLI Option if it was not provided:

            **Example**

            ```python
            @app.command()
            def main(name: str, lastname: Annotated[str, typer.Option(prompt=True)]):
                print(f"Hello {name} {lastname}")
            ```
            """
        ),
    ] = False,
    confirmation_prompt: Annotated[
        bool,
        Doc(
            """
            When set to `True`, a user will need to type a prompted value twice (may be useful for passwords etc.).

            **Example**

            ```python
            @app.command()
            def main(project: Annotated[str, typer.Option(prompt=True, confirmation_prompt=True)]):
                print(f"Deleting project {project}")
            ```
            """
        ),
    ] = False,
    prompt_required: Annotated[
        bool,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.

            ---

            If this is `False` then a prompt is only shown if the option's flag is given without a value.
            """
        ),
    ] = True,
    hide_input: Annotated[
        bool,
        Doc(
            """
            When you've configured a prompt, for instance for [querying a password](https://typer.tiangolo.com/tutorial/options/password/),
            don't show anything on the screen while the user is typing the value.

            **Example**

            ```python
            @app.command()
            def login(
                name: str,
                password: Annotated[str, typer.Option(prompt=True, hide_input=True)],
            ):
                print(f"Hello {name}. Doing something very secure with password.")
            ```
            """
        ),
    ] = False,
    # TODO: remove is_flag and flag_value in a future release
    is_flag: Annotated[
        bool | None,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.
            It is however not fully functional, and will likely be removed in future versions.
            """
        ),
    ] = None,
    flag_value: Annotated[
        Any | None,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.
            It is however not fully functional, and will likely be removed in future versions.
            """
        ),
    ] = None,
    count: Annotated[
        bool,
        Doc(
            """
            Make a CLI Option work as a [counter](https://typer.tiangolo.com/tutorial/parameter-types/number/#counter-cli-options).
            The CLI option will have the `int` value representing the number of times the option was used on the command line.

            **Example**

            ```python
            @app.command()
            def main(verbose: Annotated[int, typer.Option("--verbose", "-v", count=True)] = 0):
                print(f"Verbose level is {verbose}")
            ```
            """
        ),
    ] = False,
    allow_from_autoenv: Annotated[
        bool,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.

            ---

            If this is enabled then the value of this parameter will be pulled from an environment variable in case a prefix is defined on the context.
            """
        ),
    ] = True,
    help: Annotated[
        str | None,
        Doc(
            """
            Help text for this CLI Option.
            See [the tutorial about CLI Options with help](https://typer.tiangolo.com/tutorial/options/help/) for more dedails.

            **Example**

            ```python
            @app.command()
            def greet(name: Annotated[str, typer.Option(help="Person to greet")] = "Deadpool"):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = None,
    hidden: Annotated[
        bool,
        Doc(
            """
            Hide this CLI Option from [help outputs](https://typer.tiangolo.com/tutorial/options/help). `False` by default.

            **Example**

            ```python
            @app.command()
            def greet(name: Annotated[str, typer.Option(hidden=True)] = "Deadpool"):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = False,
    show_choices: Annotated[
        bool,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.

            ---

            When set to `False`, this suppresses choices from being displayed inline when `prompt` is used.
            """
        ),
    ] = True,
    show_envvar: Annotated[
        bool,
        Doc(
            """
            When an ["envvar"](https://typer.tiangolo.com/tutorial/arguments/envvar) is defined, prevent it from showing up in the help text:

            **Example**

            ```python
            @app.command()
            def main(user: Annotated[str, typer.Option(envvar="ME", show_envvar=False)]):
                print(f"Hello {user}")
            ```
            """
        ),
    ] = True,
    # Choice
    case_sensitive: Annotated[
        bool,
        Doc(
            """
            For a CLI Option representing an [Enum (choice)](https://typer.tiangolo.com/tutorial/parameter-types/enum),
            you can allow case-insensitive matching with this parameter:

            **Example**

            ```python
            from enum import Enum

            class NeuralNetwork(str, Enum):
                simple = "simple"
                conv = "conv"
                lstm = "lstm"

            @app.command()
            def main(
                network: Annotated[NeuralNetwork, typer.Option(case_sensitive=False)]):
                print(f"Training neural network of type: {network.value}")
            ```

            With this setting, "LSTM" or "lstm" will both be valid values that will be resolved to `NeuralNetwork.lstm`.
            """
        ),
    ] = True,
    # Numbers
    min: Annotated[
        int | float | None,
        Doc(
            """
            For a CLI Option representing a [number](https://typer.tiangolo.com/tutorial/parameter-types/number/) (`int` or `float`),
            you can define numeric validations with `min` and `max` values:

            **Example**

            ```python
            @app.command()
            def main(
                user: Annotated[str, typer.Argument()],
                user_id: Annotated[int, typer.Option(min=1, max=1000)],
            ):
                print(f"ID for {user} is {user_id}")
            ```

            If the user attempts to input an invalid number, an error will be shown, explaining why the value is invalid.
            """
        ),
    ] = None,
    max: Annotated[
        int | float | None,
        Doc(
            """
            For a CLI Option representing a [number](https://typer.tiangolo.com/tutorial/parameter-types/number/) (`int` or `float`),
            you can define numeric validations with `min` and `max` values:

            **Example**

            ```python
            @app.command()
            def main(
                user: Annotated[str, typer.Argument()],
                user_id: Annotated[int, typer.Option(min=1, max=1000)],
            ):
                print(f"ID for {user} is {user_id}")
            ```

            If the user attempts to input an invalid number, an error will be shown, explaining why the value is invalid.
            """
        ),
    ] = None,
    clamp: Annotated[
        bool,
        Doc(
            """
            For a CLI Option representing a [number](https://typer.tiangolo.com/tutorial/parameter-types/number/) and that is bounded by using `min` and/or `max`,
            you can opt to use the closest minimum or maximum value instead of raising an error when the value is out of bounds. This is done by setting `clamp` to `True`.

            **Example**

            ```python
            @app.command()
            def main(
                user: Annotated[str, typer.Argument()],
                user_id: Annotated[int, typer.Option(min=1, max=1000, clamp=True)],
            ):
                print(f"ID for {user} is {user_id}")
            ```

            If the user attempts to input 3420 for `user_id`, this will internally be converted to `1000`.
            """
        ),
    ] = False,
    # DateTime
    formats: Annotated[
        list[str] | None,
        Doc(
            """
            For a CLI Option representing a [DateTime object](https://typer.tiangolo.com/tutorial/parameter-types/datetime),
            you can customize the formats that can be parsed automatically:

            **Example**

            ```python
            from datetime import datetime

            @app.command()
            def main(
                birthday: Annotated[
                    datetime,
                    typer.Option(
                        formats=["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"]
                    ),
                ],
            ):
                print(f"Birthday defined at: {birthday}")
            ```
            """
        ),
    ] = None,
    # File
    mode: Annotated[
        str | None,
        Doc(
            """
            For a CLI Option representing a [File object](https://typer.tiangolo.com/tutorial/parameter-types/file/),
            you can customize the mode to open the file with. If unset, Typer will set a [sensible value by default](https://typer.tiangolo.com/tutorial/parameter-types/file/#advanced-mode).

            **Example**

            ```python
            @app.command()
            def main(config: Annotated[typer.FileText, typer.Option(mode="a")]):
                config.write("This is a single line\\n")
                print("Config line written")
            ```
            """
        ),
    ] = None,
    encoding: Annotated[
        str | None,
        Doc(
            """
            Customize the encoding of this CLI Option represented by a [File object](https://typer.tiangolo.com/tutorial/parameter-types/file/).

            **Example**

            ```python
            @app.command()
            def main(config: Annotated[typer.FileText, typer.Option(encoding="utf-8")]):
                config.write("All the text gets written\\n")
            ```
            """
        ),
    ] = None,
    errors: Annotated[
        str | None,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.

            ---

            The error handling mode.
            """
        ),
    ] = "strict",
    lazy: Annotated[
        bool | None,
        Doc(
            """
            For a CLI Option representing a [File object](https://typer.tiangolo.com/tutorial/parameter-types/file/),
            by default the file will not be created until you actually start writing to it.
            You can change this behaviour by setting this parameter.
            By default, it's set to `True` for writing and to `False` for reading.

            **Example**

            ```python
            @app.command()
            def main(config: Annotated[typer.FileText, typer.Option(mode="a", lazy=False)]):
                config.write("This is a single line\\n")
                print("Config line written")
            ```
            """
        ),
    ] = None,
    atomic: Annotated[
        bool,
        Doc(
            """
            For a CLI Option representing a [File object](https://typer.tiangolo.com/tutorial/parameter-types/file/),
            you can ensure that all write instructions first go into a temporal file, and are only moved to the final destination after completing
            by setting `atomic` to `True`. This can be useful for files with potential concurrent access.

            **Example**

            ```python
            @app.command()
            def main(config: Annotated[typer.FileText, typer.Option(mode="a", atomic=True)]):
                config.write("All the text")
            ```
            """
        ),
    ] = False,
    # Path
    exists: Annotated[
        bool,
        Doc(
            """
            When set to `True` for a [`Path` CLI Option](https://typer.tiangolo.com/tutorial/parameter-types/path/),
            additional validation is performed to check that the file or directory exists. If not, the value will be invalid.

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Option(exists=True)]):
                text = config.read_text()
                print(f"Config file contents: {text}")
            ```
            """
        ),
    ] = False,
    file_okay: Annotated[
        bool,
        Doc(
            """
            Determine whether or not a [`Path` CLI Option](https://typer.tiangolo.com/tutorial/parameter-types/path/)
            is allowed to refer to a file. When this is set to `False`, the application will raise a validation error when a path to a file is given.

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Option(exists=True, file_okay=False)]):
                print(f"Directory listing: {[x.name for x in config.iterdir()]}")
            ```
            """
        ),
    ] = True,
    dir_okay: Annotated[
        bool,
        Doc(
            """
            Determine whether or not a [`Path` CLI Option](https://typer.tiangolo.com/tutorial/parameter-types/path/)
            is allowed to refer to a directory. When this is set to `False`, the application will raise a validation error when a path to a directory is given.

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]):
                text = config.read_text()
                print(f"Config file contents: {text}")
            ```
            """
        ),
    ] = True,
    writable: Annotated[
        bool,
        Doc(
            """
            Whether or not to perform a writable check for this [`Path` CLI Option](https://typer.tiangolo.com/tutorial/parameter-types/path/).

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Option(writable=True)]):
                config.write_text("All the text")
            ```
            """
        ),
    ] = False,
    readable: Annotated[
        bool,
        Doc(
            """
            Whether or not to perform a readable check for this [`Path` CLI Option](https://typer.tiangolo.com/tutorial/parameter-types/path/).

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Option(readable=True)]):
                config.read_text("All the text")
            ```
            """
        ),
    ] = True,
    resolve_path: Annotated[
        bool,
        Doc(
            """
            Whether or not to fully resolve the path of this [`Path` CLI Option](https://typer.tiangolo.com/tutorial/parameter-types/path/),
            meaning that the path becomes absolute and symlinks are resolved.

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Option(resolve_path=True)]):
                config.read_text("All the text")
            ```
            """
        ),
    ] = False,
    allow_dash: Annotated[
        bool,
        Doc(
            """
            When set to `True`, a single dash for this [`Path` CLI Option](https://typer.tiangolo.com/tutorial/parameter-types/path/)
            would be a valid value, indicating standard streams. This is a more advanced use-case.
            """
        ),
    ] = False,
    path_type: Annotated[
        None | type[str] | type[bytes],
        Doc(
            """
             A string type that will be used to represent this [`Path` argument](https://typer.tiangolo.com/tutorial/parameter-types/path/).
             The default is `None` which means the return value will be either bytes or unicode, depending on what makes most sense given the input data.
             This is a more advanced use-case.
            """
        ),
    ] = None,
    # Rich settings
    rich_help_panel: Annotated[
        str | None,
        Doc(
            """
            Set the panel name where you want this CLI Option to be shown in the [help text](https://typer.tiangolo.com/tutorial/arguments/help).

            **Example**

            ```python
            @app.command()
            def main(
                name: Annotated[str, typer.Argument(help="Who to greet")],
                age: Annotated[str, typer.Option(help="Their age", rich_help_panel="Data")],
            ):
                print(f"Hello {name} of age {age}")
            ```
            """
        ),
    ] = None,
) -> Any:
    """
    A [CLI Option](https://typer.tiangolo.com/tutorial/options) is a parameter to your command line application that is called with a single or double dash, something like `--verbose` or `-v`.

    Often, CLI Options are optional, meaning that users can omit them from the command. However, you can set them to be required by using `Annotated`
    and omitting a default value.

    ## Example

    ```python
    @app.command()
    def register(
        user: Annotated[str, typer.Argument()],
        age: Annotated[int, typer.Option(min=18)],
    ):
        print(f"User is {user}")
        print(f"--age is {age}")
    ```

    Note how in this example, `--age` is a required CLI Option.
    """
    return OptionInfo(
        # Parameter
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
        # Option
        show_default=show_default,
        prompt=prompt,
        confirmation_prompt=confirmation_prompt,
        prompt_required=prompt_required,
        hide_input=hide_input,
        is_flag=is_flag,
        flag_value=flag_value,
        count=count,
        allow_from_autoenv=allow_from_autoenv,
        help=help,
        hidden=hidden,
        show_choices=show_choices,
        show_envvar=show_envvar,
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


# Overload for Argument created with custom type 'parser'
@overload
def Argument(
    # Parameter
    default: Any | None = ...,
    *,
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
) -> Any: ...


# Overload for Argument created with custom type 'click_type'
@overload
def Argument(
    # Parameter
    default: Any | None = ...,
    *,
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
) -> Any: ...


def Argument(
    # Parameter
    default: Annotated[
        Any | None,
        Doc(
            """
            By default, CLI arguments are required. However, by giving them a default value they become [optional](https://typer.tiangolo.com/tutorial/arguments/optional):

            **Example**

            ```python
            @app.command()
            def main(name: str = typer.Argument("World")):
                print(f"Hello {name}!")
            ```

            Note that this usage is deprecated, and we recommend to use `Annotated` instead:
            ```python
            @app.command()
            def main(name: Annotated[str, typer.Argument()] = "World"):
                print(f"Hello {name}!")
            ```
            """
        ),
    ] = ...,
    *,
    callback: Annotated[
        Callable[..., Any] | None,
        Doc(
            """
            Add a callback to this CLI Argument, to execute additional logic with the value received from the terminal.
            See [the tutorial about callbacks](https://typer.tiangolo.com/tutorial/options/callback-and-context/) for more details.

            **Example**

            ```python
            def name_callback(value: str):
                if value != "Deadpool":
                    raise typer.BadParameter("Only Deadpool is allowed")
                return value

            @app.command()
            def main(name: Annotated[str, typer.Argument(callback=name_callback)]):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = None,
    metavar: Annotated[
        str | None,
        Doc(
            """
            Customize the name displayed in the help text to represent this CLI Argument.
            By default, it will be the same name you declared, in uppercase.
            See [the tutorial about CLI Arguments with Help](https://typer.tiangolo.com/tutorial/arguments/help/#custom-help-name-metavar) for more details.

            **Example**

            ```python
            @app.command()
            def main(name: Annotated[str, typer.Argument(metavar="✨username✨")]):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = None,
    expose_value: Annotated[
        bool,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.

            ---

            If this is `True` then the value is passed onwards to the command callback and stored on the context, otherwise it’s skipped.
            """
        ),
    ] = True,
    is_eager: Annotated[
        bool,
        Doc(
            """
            Set an argument to "eager" to ensure it gets processed before other CLI parameters. This could be relevant when there are other parameters with callbacks that could exit the program early.
            For more information and an extended example, see the documentation [here](https://typer.tiangolo.com/tutorial/options/version/#fix-with-is_eager).
            """
        ),
    ] = False,
    envvar: Annotated[
        str | list[str] | None,
        Doc(
            """
            Configure an argument to read a value from an environment variable if it is not provided in the command line as a CLI argument.
            For more information, see the [documentation on Environment Variables](https://typer.tiangolo.com/tutorial/arguments/envvar/).

            **Example**

            ```python
            @app.command()
            def main(name: Annotated[str, typer.Argument(envvar="ME")]):
                print(f"Hello Mr. {name}")
            ```
            """
        ),
    ] = None,
    # TODO: Remove shell_complete in a future version (after 0.16.0)
    shell_complete: Annotated[
        Callable[
            [click.Context, click.Parameter, str],
            list["click.shell_completion.CompletionItem"] | list[str],
        ]
        | None,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.
            It is however not fully functional, and will likely be removed in future versions.
            """
        ),
    ] = None,
    autocompletion: Annotated[
        Callable[..., Any] | None,
        Doc(
            """
            Provide a custom function that helps to autocomplete the values of this CLI Argument.
            See [the tutorial on parameter autocompletion](https://typer.tiangolo.com/tutorial/options-autocompletion) for more details.

            **Example**

            ```python
            def complete():
                return ["Me", "Myself", "I"]

            @app.command()
            def main(name: Annotated[str, typer.Argument(autocompletion=complete)]):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = None,
    default_factory: Annotated[
        Callable[[], Any] | None,
        Doc(
            """
            Provide a custom function that dynamically generates a [default](https://typer.tiangolo.com/tutorial/arguments/default) for this CLI Argument.

            **Example**

            ```python
            def get_name():
                return random.choice(["Me", "Myself", "I"])

            @app.command()
            def main(name: Annotated[str, typer.Argument(default_factory=get_name)]):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = None,
    # Custom type
    parser: Annotated[
        Callable[[str], Any] | None,
        Doc(
            """
            Use your own custom types in Typer applications by defining a `parser` function that parses input into your own types:

            **Example**

            ```python
            class CustomClass:
                def __init__(self, value: str):
                    self.value = value

                def __str__(self):
                    return f"<CustomClass: value={self.value}>"

            def my_parser(value: str):
                return CustomClass(value * 2)

            @app.command()
            def main(arg: Annotated[CustomClass, typer.Argument(parser=my_parser):
                print(f"arg is {arg}")
            ```
            """
        ),
    ] = None,
    click_type: Annotated[
        click.ParamType | None,
        Doc(
            """
            Define this parameter to use a [custom Click type](https://click.palletsprojects.com/en/stable/parameters/#implementing-custom-types) in your Typer applications.

            **Example**

            ```python
            class MyClass:
                def __init__(self, value: str):
                    self.value = value

                def __str__(self):
                    return f"<MyClass: value={self.value}>"

            class MyParser(click.ParamType):
                name = "MyClass"

                def convert(self, value, param, ctx):
                    return MyClass(value * 3)

            @app.command()
            def main(arg: Annotated[MyClass, typer.Argument(click_type=MyParser())]):
                print(f"arg is {arg}")
            ```
            """
        ),
    ] = None,
    # TyperArgument
    show_default: Annotated[
        bool | str,
        Doc(
            """
            When set to `False`, don't show the default value of this CLI Argument in the [help text](https://typer.tiangolo.com/tutorial/arguments/help/).

            **Example**

            ```python
            @app.command()
            def main(name: Annotated[str, typer.Argument(show_default=False)] = "Rick"):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = True,
    show_choices: Annotated[
        bool,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.

            ---

            When set to `False`, this suppresses choices from being displayed inline when `prompt` is used.
            """
        ),
    ] = True,
    show_envvar: Annotated[
        bool,
        Doc(
            """
            When an ["envvar"](https://typer.tiangolo.com/tutorial/arguments/envvar) is defined, prevent it from showing up in the help text:

            **Example**

            ```python
            @app.command()
            def main(name: Annotated[str, typer.Argument(envvar="ME", show_envvar=False)]):
                print(f"Hello Mr. {name}")
            ```
            """
        ),
    ] = True,
    help: Annotated[
        str | None,
        Doc(
            """
            Help text for this CLI Argument.
            See [the tutorial about CLI Arguments with help](https://typer.tiangolo.com/tutorial/arguments/help/) for more dedails.

            **Example**

            ```python
            @app.command()
            def greet(name: Annotated[str, typer.Argument(help="Person to greet")]):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = None,
    hidden: Annotated[
        bool,
        Doc(
            """
            Hide this CLI Argument from [help outputs](https://typer.tiangolo.com/tutorial/arguments/help). `False` by default.

            **Example**

            ```python
            @app.command()
            def main(name: Annotated[str, typer.Argument(hidden=True)] = "World"):
                print(f"Hello {name}")
            ```
            """
        ),
    ] = False,
    # Choice
    case_sensitive: Annotated[
        bool,
        Doc(
            """
            For a CLI Argument representing an [Enum (choice)](https://typer.tiangolo.com/tutorial/parameter-types/enum),
            you can allow case-insensitive matching with this parameter:

            **Example**

            ```python
            from enum import Enum

            class NeuralNetwork(str, Enum):
                simple = "simple"
                conv = "conv"
                lstm = "lstm"

            @app.command()
            def main(
                network: Annotated[NeuralNetwork, typer.Argument(case_sensitive=False)]):
                print(f"Training neural network of type: {network.value}")
            ```

            With this setting, "LSTM" or "lstm" will both be valid values that will be resolved to `NeuralNetwork.lstm`.
            """
        ),
    ] = True,
    # Numbers
    min: Annotated[
        int | float | None,
        Doc(
            """
            For a CLI Argument representing a [number](https://typer.tiangolo.com/tutorial/parameter-types/number/) (`int` or `float`),
            you can define numeric validations with `min` and `max` values:

            **Example**

            ```python
            @app.command()
            def main(
                user: Annotated[str, typer.Argument()],
                user_id: Annotated[int, typer.Argument(min=1, max=1000)],
            ):
                print(f"ID for {user} is {user_id}")
            ```

            If the user attempts to input an invalid number, an error will be shown, explaining why the value is invalid.
            """
        ),
    ] = None,
    max: Annotated[
        int | float | None,
        Doc(
            """
            For a CLI Argument representing a [number](https://typer.tiangolo.com/tutorial/parameter-types/number/) (`int` or `float`),
            you can define numeric validations with `min` and `max` values:

            **Example**

            ```python
            @app.command()
            def main(
                user: Annotated[str, typer.Argument()],
                user_id: Annotated[int, typer.Argument(min=1, max=1000)],
            ):
                print(f"ID for {user} is {user_id}")
            ```

            If the user attempts to input an invalid number, an error will be shown, explaining why the value is invalid.
            """
        ),
    ] = None,
    clamp: Annotated[
        bool,
        Doc(
            """
            For a CLI Argument representing a [number](https://typer.tiangolo.com/tutorial/parameter-types/number/) and that is bounded by using `min` and/or `max`,
            you can opt to use the closest minimum or maximum value instead of raising an error. This is done by setting `clamp` to `True`.

            **Example**

            ```python
            @app.command()
            def main(
                user: Annotated[str, typer.Argument()],
                user_id: Annotated[int, typer.Argument(min=1, max=1000, clamp=True)],
            ):
                print(f"ID for {user} is {user_id}")
            ```

            If the user attempts to input 3420 for `user_id`, this will internally be converted to `1000`.
            """
        ),
    ] = False,
    # DateTime
    formats: Annotated[
        list[str] | None,
        Doc(
            """
            For a CLI Argument representing a [DateTime object](https://typer.tiangolo.com/tutorial/parameter-types/datetime),
            you can customize the formats that can be parsed automatically:

            **Example**

            ```python
            from datetime import datetime

            @app.command()
            def main(
                birthday: Annotated[
                    datetime,
                    typer.Argument(
                        formats=["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"]
                    ),
                ],
            ):
                print(f"Birthday defined at: {birthday}")
            ```
            """
        ),
    ] = None,
    # File
    mode: Annotated[
        str | None,
        Doc(
            """
            For a CLI Argument representing a [File object](https://typer.tiangolo.com/tutorial/parameter-types/file/),
            you can customize the mode to open the file with. If unset, Typer will set a [sensible value by default](https://typer.tiangolo.com/tutorial/parameter-types/file/#advanced-mode).

            **Example**

            ```python
            @app.command()
            def main(config: Annotated[typer.FileText, typer.Argument(mode="a")]):
                config.write("This is a single line\\n")
                print("Config line written")
            ```
            """
        ),
    ] = None,
    encoding: Annotated[
        str | None,
        Doc(
            """
            Customize the encoding of this CLI Argument represented by a [File object](https://typer.tiangolo.com/tutorial/parameter-types/file/).

            **Example**

            ```python
            @app.command()
            def main(config: Annotated[typer.FileText, typer.Argument(encoding="utf-8")]):
                config.write("All the text gets written\\n")
            ```
            """
        ),
    ] = None,
    errors: Annotated[
        str | None,
        Doc(
            """
            **Note**: you probably shouldn't use this parameter, it is inherited from Click and supported for compatibility.

            ---

            The error handling mode.
            """
        ),
    ] = "strict",
    lazy: Annotated[
        bool | None,
        Doc(
            """
            For a CLI Argument representing a [File object](https://typer.tiangolo.com/tutorial/parameter-types/file/),
            by default the file will not be created until you actually start writing to it.
            You can change this behaviour by setting this parameter.
            By default, it's set to `True` for writing and to `False` for reading.

            **Example**

            ```python
            @app.command()
            def main(config: Annotated[typer.FileText, typer.Argument(mode="a", lazy=False)]):
                config.write("This is a single line\\n")
                print("Config line written")
            ```
            """
        ),
    ] = None,
    atomic: Annotated[
        bool,
        Doc(
            """
            For a CLI Argument representing a [File object](https://typer.tiangolo.com/tutorial/parameter-types/file/),
            you can ensure that all write instructions first go into a temporal file, and are only moved to the final destination after completing
            by setting `atomic` to `True`. This can be useful for files with potential concurrent access.

            **Example**

            ```python
            @app.command()
            def main(config: Annotated[typer.FileText, typer.Argument(mode="a", atomic=True)]):
                config.write("All the text")
            ```
            """
        ),
    ] = False,
    # Path
    exists: Annotated[
        bool,
        Doc(
            """
            When set to `True` for a [`Path` argument](https://typer.tiangolo.com/tutorial/parameter-types/path/),
            additional validation is performed to check that the file or directory exists. If not, the value will be invalid.

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Argument(exists=True)]):
                text = config.read_text()
                print(f"Config file contents: {text}")
            ```
            """
        ),
    ] = False,
    file_okay: Annotated[
        bool,
        Doc(
            """
            Determine whether or not a [`Path` argument](https://typer.tiangolo.com/tutorial/parameter-types/path/)
            is allowed to refer to a file. When this is set to `False`, the application will raise a validation error when a path to a file is given.

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Argument(exists=True, file_okay=False)]):
                print(f"Directory listing: {[x.name for x in config.iterdir()]}")
            ```
            """
        ),
    ] = True,
    dir_okay: Annotated[
        bool,
        Doc(
            """
            Determine whether or not a [`Path` argument](https://typer.tiangolo.com/tutorial/parameter-types/path/)
            is allowed to refer to a directory. When this is set to `False`, the application will raise a validation error when a path to a directory is given.

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]):
                text = config.read_text()
                print(f"Config file contents: {text}")
            ```
            """
        ),
    ] = True,
    writable: Annotated[
        bool,
        Doc(
            """
            Whether or not to perform a writable check for this [`Path` argument](https://typer.tiangolo.com/tutorial/parameter-types/path/).

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Argument(writable=True)]):
                config.write_text("All the text")
            ```
            """
        ),
    ] = False,
    readable: Annotated[
        bool,
        Doc(
            """
            Whether or not to perform a readable check for this [`Path` argument](https://typer.tiangolo.com/tutorial/parameter-types/path/).

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Argument(readable=True)]):
                config.read_text("All the text")
            ```
            """
        ),
    ] = True,
    resolve_path: Annotated[
        bool,
        Doc(
            """
            Whether or not to fully resolve the path of this [`Path` argument](https://typer.tiangolo.com/tutorial/parameter-types/path/),
            meaning that the path becomes absolute and symlinks are resolved.

            **Example**

            ```python
            from pathlib import Path

            @app.command()
            def main(config: Annotated[Path, typer.Argument(resolve_path=True)]):
                config.read_text("All the text")
            ```
            """
        ),
    ] = False,
    allow_dash: Annotated[
        bool,
        Doc(
            """
            When set to `True`, a single dash for this [`Path` argument](https://typer.tiangolo.com/tutorial/parameter-types/path/)
            would be a valid value, indicating standard streams. This is a more advanced use-case.
            """
        ),
    ] = False,
    path_type: Annotated[
        None | type[str] | type[bytes],
        Doc(
            """
            A string type that will be used to represent this [`Path` argument](https://typer.tiangolo.com/tutorial/parameter-types/path/).
            The default is `None` which means the return value will be either bytes or unicode, depending on what makes most sense given the input data.
            This is a more advanced use-case.
            """
        ),
    ] = None,
    # Rich settings
    rich_help_panel: Annotated[
        str | None,
        Doc(
            """
            Set the panel name where you want this CLI Argument to be shown in the [help text](https://typer.tiangolo.com/tutorial/arguments/help).

            **Example**

            ```python
            @app.command()
            def main(
                name: Annotated[str, typer.Argument(help="Who to greet")],
                age: Annotated[str, typer.Option(help="Their age", rich_help_panel="Data")],
            ):
                print(f"Hello {name} of age {age}")
            ```
            """
        ),
    ] = None,
) -> Any:
    """
    A [CLI Argument](https://typer.tiangolo.com/tutorial/arguments) is a positional parameter to your command line application.

    Often, CLI Arguments are required, meaning that users have to specify them. However, you can set them to be optional by defining a default value:

    ## Example

    ```python
    @app.command()
    def main(name: Annotated[str, typer.Argument()] = "World"):
        print(f"Hello {name}!")
    ```

    Note how in this example, if `name` is not specified on the command line, the application will still execute normally and print "Hello World!".
    """
    return ArgumentInfo(
        # Parameter
        default=default,
        # Arguments can only have one param declaration
        # it will be generated from the param name
        param_decls=None,
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
