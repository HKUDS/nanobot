"""Command-line interface settings source."""

from __future__ import annotations as _annotations

import json
import re
import shlex
import sys
import typing
from argparse import (
    SUPPRESS,
    ArgumentParser,
    BooleanOptionalAction,
    Namespace,
    RawDescriptionHelpFormatter,
    _SubParsersAction,
)
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from functools import cached_property
from textwrap import dedent
from types import SimpleNamespace
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Generic,
    Literal,
    NoReturn,
    TypeVar,
    cast,
    get_args,
    get_origin,
    overload,
)

import typing_extensions
from pydantic import AliasChoices, AliasPath, BaseModel, Field, PrivateAttr
from pydantic._internal._repr import Representation
from pydantic._internal._utils import is_model_class
from pydantic.dataclasses import is_pydantic_dataclass
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from typing_inspection import typing_objects
from typing_inspection.introspection import is_union_origin

from ...exceptions import SettingsError
from ...utils import _lenient_issubclass, _WithArgsTypes
from ..types import (
    ForceDecode,
    NoDecode,
    PydanticModel,
    _CliExplicitFlag,
    _CliImplicitFlag,
    _CliPositionalArg,
    _CliSubCommand,
    _CliUnknownArgs,
)
from ..utils import (
    _annotation_contains_types,
    _annotation_enum_val_to_name,
    _get_alias_names,
    _get_model_fields,
    _is_function,
    _strip_annotated,
    parse_env_vars,
)
from .env import EnvSettingsSource

if TYPE_CHECKING:
    from pydantic_settings.main import BaseSettings


class _CliInternalArgParser(ArgumentParser):
    def __init__(self, cli_exit_on_error: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cli_exit_on_error = cli_exit_on_error

    def error(self, message: str) -> NoReturn:
        if not self._cli_exit_on_error:
            raise SettingsError(f'error parsing CLI: {message}')
        super().error(message)


class CliMutuallyExclusiveGroup(BaseModel):
    pass


class _CliArg(BaseModel):
    model: Any
    field_name: str
    arg_prefix: str
    case_sensitive: bool
    hide_none_type: bool
    kebab_case: bool | Literal['all', 'no_enums'] | None
    enable_decoding: bool | None
    env_prefix_len: int
    args: list[str] = []
    kwargs: dict[str, Any] = {}

    _alias_names: tuple[str, ...] = PrivateAttr(())
    _alias_paths: dict[str, int | None] = PrivateAttr({})
    _is_alias_path_only: bool = PrivateAttr(False)
    _field_info: FieldInfo = PrivateAttr()

    def __init__(
        self,
        field_info: FieldInfo,
        parser_map: defaultdict[str | FieldInfo, dict[int | None | str, _CliArg]],
        **values: Any,
    ) -> None:
        super().__init__(**values)
        self._field_info = field_info
        self._alias_names, self._is_alias_path_only = _get_alias_names(
            self.field_name, self.field_info, alias_path_args=self._alias_paths, case_sensitive=self.case_sensitive
        )

        alias_path_dests = {f'{self.arg_prefix}{name}': index for name, index in self._alias_paths.items()}
        if self.subcommand_dest:
            for sub_model in self.sub_models:
                subcommand_alias = self.subcommand_alias(sub_model)
                parser_map[self.subcommand_dest][subcommand_alias] = self.model_copy(update={'args': [], 'kwargs': {}})
                parser_map[self.field_info][subcommand_alias] = parser_map[self.subcommand_dest][subcommand_alias]
        elif self.dest not in alias_path_dests:
            parser_map[self.dest][None] = self
            parser_map[self.field_info][None] = parser_map[self.dest][None]
        for alias_path_dest, index in alias_path_dests.items():
            parser_map[alias_path_dest][index] = self.model_copy(update={'args': [], 'kwargs': {}})
            parser_map[self.field_info][index] = parser_map[alias_path_dest][index]

    @classmethod
    def get_kebab_case(cls, name: str, kebab_case: bool | Literal['all', 'no_enums'] | None) -> str:
        return name.replace('_', '-') if kebab_case not in (None, False) else name

    @classmethod
    def get_enum_names(
        cls, annotation: type[Any], kebab_case: bool | Literal['all', 'no_enums'] | None
    ) -> tuple[str, ...]:
        enum_names: tuple[str, ...] = ()
        annotation = _strip_annotated(annotation)
        for type_ in get_args(annotation):
            enum_names += cls.get_enum_names(type_, kebab_case)
        if annotation and _lenient_issubclass(annotation, Enum):
            enum_names += tuple(cls.get_kebab_case(val.name, kebab_case == 'all') for val in annotation)
        return enum_names

    def subcommand_alias(self, sub_model: type[BaseModel]) -> str:
        return self.get_kebab_case(
            sub_model.__name__ if len(self.sub_models) > 1 else self.preferred_alias, self.kebab_case
        )

    @cached_property
    def field_info(self) -> FieldInfo:
        return self._field_info

    @cached_property
    def subcommand_dest(self) -> str | None:
        return f'{self.arg_prefix}:subcommand' if _CliSubCommand in self.field_info.metadata else None

    @cached_property
    def dest(self) -> str:
        if (
            not self.subcommand_dest
            and self.arg_prefix
            and self.field_info.validation_alias is not None
            and not self.is_parser_submodel
        ):
            # Strip prefix if validation alias is set and value is not complex.
            # Related https://github.com/pydantic/pydantic-settings/pull/25
            return f'{self.arg_prefix}{self.preferred_alias}'[self.env_prefix_len :]
        return f'{self.arg_prefix}{self.preferred_alias}'

    @cached_property
    def preferred_arg_name(self) -> str:
        return self.args[0].replace('_', '-') if self.kebab_case else self.args[0]

    @cached_property
    def sub_models(self) -> list[type[BaseModel]]:
        field_types: tuple[Any, ...] = (
            (self.field_info.annotation,)
            if not get_args(self.field_info.annotation)
            else get_args(self.field_info.annotation)
        )
        if self.hide_none_type:
            field_types = tuple([type_ for type_ in field_types if type_ is not type(None)])

        sub_models: list[type[BaseModel]] = []
        for type_ in field_types:
            if _annotation_contains_types(type_, (_CliSubCommand,), is_include_origin=False):
                raise SettingsError(
                    f'CliSubCommand is not outermost annotation for {self.model.__name__}.{self.field_name}'
                )
            elif _annotation_contains_types(type_, (_CliPositionalArg,), is_include_origin=False):
                raise SettingsError(
                    f'CliPositionalArg is not outermost annotation for {self.model.__name__}.{self.field_name}'
                )
            if is_model_class(_strip_annotated(type_)) or is_pydantic_dataclass(_strip_annotated(type_)):
                sub_models.append(_strip_annotated(type_))
        return sub_models

    @cached_property
    def alias_names(self) -> tuple[str, ...]:
        return self._alias_names

    @cached_property
    def alias_paths(self) -> dict[str, int | None]:
        return self._alias_paths

    @cached_property
    def preferred_alias(self) -> str:
        return self._alias_names[0]

    @cached_property
    def is_alias_path_only(self) -> bool:
        return self._is_alias_path_only

    @cached_property
    def is_append_action(self) -> bool:
        return not self.subcommand_dest and _annotation_contains_types(
            self.field_info.annotation, (list, set, dict, Sequence, Mapping), is_strip_annotated=True
        )

    @cached_property
    def is_parser_submodel(self) -> bool:
        return not self.subcommand_dest and bool(self.sub_models) and not self.is_append_action

    @cached_property
    def is_no_decode(self) -> bool:
        return self.field_info is not None and (
            NoDecode in self.field_info.metadata
            or (self.enable_decoding is False and ForceDecode not in self.field_info.metadata)
        )


T = TypeVar('T')
CliSubCommand = Annotated[T | None, _CliSubCommand]
CliPositionalArg = Annotated[T, _CliPositionalArg]
_CliBoolFlag = TypeVar('_CliBoolFlag', bound=bool)
CliImplicitFlag = Annotated[_CliBoolFlag, _CliImplicitFlag]
CliExplicitFlag = Annotated[_CliBoolFlag, _CliExplicitFlag]
CLI_SUPPRESS = SUPPRESS
CliSuppress = Annotated[T, CLI_SUPPRESS]
CliUnknownArgs = Annotated[list[str], Field(default=[]), _CliUnknownArgs, NoDecode]


class CliSettingsSource(EnvSettingsSource, Generic[T]):
    """
    Source class for loading settings values from CLI.

    Note:
        A `CliSettingsSource` connects with a `root_parser` object by using the parser methods to add
        `settings_cls` fields as command line arguments. The `CliSettingsSource` internal parser representation
        is based upon the `argparse` parsing library, and therefore, requires the parser methods to support
        the same attributes as their `argparse` library counterparts.

    Args:
        cli_prog_name: The CLI program name to display in help text. Defaults to `None` if cli_parse_args is `None`.
            Otherwise, defaults to sys.argv[0].
        cli_parse_args: The list of CLI arguments to parse. Defaults to None.
            If set to `True`, defaults to sys.argv[1:].
        cli_parse_none_str: The CLI string value that should be parsed (e.g. "null", "void", "None", etc.) into `None`
            type(None). Defaults to "null" if cli_avoid_json is `False`, and "None" if cli_avoid_json is `True`.
        cli_hide_none_type: Hide `None` values in CLI help text. Defaults to `False`.
        cli_avoid_json: Avoid complex JSON objects in CLI help text. Defaults to `False`.
        cli_enforce_required: Enforce required fields at the CLI. Defaults to `False`.
        cli_use_class_docs_for_groups: Use class docstrings in CLI group help text instead of field descriptions.
            Defaults to `False`.
        cli_exit_on_error: Determines whether or not the internal parser exits with error info when an error occurs.
            Defaults to `True`.
        cli_prefix: Prefix for command line arguments added under the root parser. Defaults to "".
        cli_flag_prefix_char: The flag prefix character to use for CLI optional arguments. Defaults to '-'.
        cli_implicit_flags: Whether `bool` fields should be implicitly converted into CLI boolean flags.
            (e.g. --flag, --no-flag). Defaults to `False`.
        cli_ignore_unknown_args: Whether to ignore unknown CLI args and parse only known ones. Defaults to `False`.
        cli_kebab_case: CLI args use kebab case. Defaults to `False`.
        cli_shortcuts: Mapping of target field name to alias names. Defaults to `None`.
        case_sensitive: Whether CLI "--arg" names should be read with case-sensitivity. Defaults to `True`.
            Note: Case-insensitive matching is only supported on the internal root parser and does not apply to CLI
            subcommands.
        root_parser: The root parser object.
        parse_args_method: The root parser parse args method. Defaults to `argparse.ArgumentParser.parse_args`.
        add_argument_method: The root parser add argument method. Defaults to `argparse.ArgumentParser.add_argument`.
        add_argument_group_method: The root parser add argument group method.
            Defaults to `argparse.ArgumentParser.add_argument_group`.
        add_parser_method: The root parser add new parser (sub-command) method.
            Defaults to `argparse._SubParsersAction.add_parser`.
        add_subparsers_method: The root parser add subparsers (sub-commands) method.
            Defaults to `argparse.ArgumentParser.add_subparsers`.
        formatter_class: A class for customizing the root parser help text. Defaults to `argparse.RawDescriptionHelpFormatter`.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        cli_prog_name: str | None = None,
        cli_parse_args: bool | list[str] | tuple[str, ...] | None = None,
        cli_parse_none_str: str | None = None,
        cli_hide_none_type: bool | None = None,
        cli_avoid_json: bool | None = None,
        cli_enforce_required: bool | None = None,
        cli_use_class_docs_for_groups: bool | None = None,
        cli_exit_on_error: bool | None = None,
        cli_prefix: str | None = None,
        cli_flag_prefix_char: str | None = None,
        cli_implicit_flags: bool | None = None,
        cli_ignore_unknown_args: bool | None = None,
        cli_kebab_case: bool | Literal['all', 'no_enums'] | None = None,
        cli_shortcuts: Mapping[str, str | list[str]] | None = None,
        case_sensitive: bool | None = True,
        root_parser: Any = None,
        parse_args_method: Callable[..., Any] | None = None,
        add_argument_method: Callable[..., Any] | None = ArgumentParser.add_argument,
        add_argument_group_method: Callable[..., Any] | None = ArgumentParser.add_argument_group,
        add_parser_method: Callable[..., Any] | None = _SubParsersAction.add_parser,
        add_subparsers_method: Callable[..., Any] | None = ArgumentParser.add_subparsers,
        formatter_class: Any = RawDescriptionHelpFormatter,
    ) -> None:
        self.cli_prog_name = (
            cli_prog_name if cli_prog_name is not None else settings_cls.model_config.get('cli_prog_name', sys.argv[0])
        )
        self.cli_hide_none_type = (
            cli_hide_none_type
            if cli_hide_none_type is not None
            else settings_cls.model_config.get('cli_hide_none_type', False)
        )
        self.cli_avoid_json = (
            cli_avoid_json if cli_avoid_json is not None else settings_cls.model_config.get('cli_avoid_json', False)
        )
        if not cli_parse_none_str:
            cli_parse_none_str = 'None' if self.cli_avoid_json is True else 'null'
        self.cli_parse_none_str = cli_parse_none_str
        self.cli_enforce_required = (
            cli_enforce_required
            if cli_enforce_required is not None
            else settings_cls.model_config.get('cli_enforce_required', False)
        )
        self.cli_use_class_docs_for_groups = (
            cli_use_class_docs_for_groups
            if cli_use_class_docs_for_groups is not None
            else settings_cls.model_config.get('cli_use_class_docs_for_groups', False)
        )
        self.cli_exit_on_error = (
            cli_exit_on_error
            if cli_exit_on_error is not None
            else settings_cls.model_config.get('cli_exit_on_error', True)
        )
        self.cli_prefix = cli_prefix if cli_prefix is not None else settings_cls.model_config.get('cli_prefix', '')
        self.cli_flag_prefix_char = (
            cli_flag_prefix_char
            if cli_flag_prefix_char is not None
            else settings_cls.model_config.get('cli_flag_prefix_char', '-')
        )
        self._cli_flag_prefix = self.cli_flag_prefix_char * 2
        if self.cli_prefix:
            if cli_prefix.startswith('.') or cli_prefix.endswith('.') or not cli_prefix.replace('.', '').isidentifier():  # type: ignore
                raise SettingsError(f'CLI settings source prefix is invalid: {cli_prefix}')
            self.cli_prefix += '.'
        self.cli_implicit_flags = (
            cli_implicit_flags
            if cli_implicit_flags is not None
            else settings_cls.model_config.get('cli_implicit_flags', False)
        )
        self.cli_ignore_unknown_args = (
            cli_ignore_unknown_args
            if cli_ignore_unknown_args is not None
            else settings_cls.model_config.get('cli_ignore_unknown_args', False)
        )
        self.cli_kebab_case = (
            cli_kebab_case if cli_kebab_case is not None else settings_cls.model_config.get('cli_kebab_case', False)
        )
        self.cli_shortcuts = (
            cli_shortcuts if cli_shortcuts is not None else settings_cls.model_config.get('cli_shortcuts', None)
        )

        case_sensitive = case_sensitive if case_sensitive is not None else True
        if not case_sensitive and root_parser is not None:
            raise SettingsError('Case-insensitive matching is only supported on the internal root parser')

        super().__init__(
            settings_cls,
            env_nested_delimiter='.',
            env_parse_none_str=self.cli_parse_none_str,
            env_parse_enums=True,
            env_prefix=self.cli_prefix,
            case_sensitive=case_sensitive,
        )

        root_parser = (
            _CliInternalArgParser(
                cli_exit_on_error=self.cli_exit_on_error,
                prog=self.cli_prog_name,
                description=None if settings_cls.__doc__ is None else dedent(settings_cls.__doc__),
                formatter_class=formatter_class,
                prefix_chars=self.cli_flag_prefix_char,
                allow_abbrev=False,
            )
            if root_parser is None
            else root_parser
        )
        self._connect_root_parser(
            root_parser=root_parser,
            parse_args_method=parse_args_method,
            add_argument_method=add_argument_method,
            add_argument_group_method=add_argument_group_method,
            add_parser_method=add_parser_method,
            add_subparsers_method=add_subparsers_method,
            formatter_class=formatter_class,
        )

        if cli_parse_args not in (None, False):
            if cli_parse_args is True:
                cli_parse_args = sys.argv[1:]
            elif not isinstance(cli_parse_args, (list, tuple)):
                raise SettingsError(
                    f'cli_parse_args must be a list or tuple of strings, received {type(cli_parse_args)}'
                )
            self._load_env_vars(parsed_args=self._parse_args(self.root_parser, cli_parse_args))

    @overload
    def __call__(self) -> dict[str, Any]: ...

    @overload
    def __call__(self, *, args: list[str] | tuple[str, ...] | bool) -> CliSettingsSource[T]:
        """
        Parse and load the command line arguments list into the CLI settings source.

        Args:
            args:
                The command line arguments to parse and load. Defaults to `None`, which means do not parse
                command line arguments. If set to `True`, defaults to sys.argv[1:]. If set to `False`, does
                not parse command line arguments.

        Returns:
            CliSettingsSource: The object instance itself.
        """
        ...

    @overload
    def __call__(self, *, parsed_args: Namespace | SimpleNamespace | dict[str, Any]) -> CliSettingsSource[T]:
        """
        Loads parsed command line arguments into the CLI settings source.

        Note:
            The parsed args must be in `argparse.Namespace`, `SimpleNamespace`, or vars dictionary
            (e.g., vars(argparse.Namespace)) format.

        Args:
            parsed_args: The parsed args to load.

        Returns:
            CliSettingsSource: The object instance itself.
        """
        ...

    def __call__(
        self,
        *,
        args: list[str] | tuple[str, ...] | bool | None = None,
        parsed_args: Namespace | SimpleNamespace | dict[str, list[str] | str] | None = None,
    ) -> dict[str, Any] | CliSettingsSource[T]:
        if args is not None and parsed_args is not None:
            raise SettingsError('`args` and `parsed_args` are mutually exclusive')
        elif args is not None:
            if args is False:
                return self._load_env_vars(parsed_args={})
            if args is True:
                args = sys.argv[1:]
            return self._load_env_vars(parsed_args=self._parse_args(self.root_parser, args))
        elif parsed_args is not None:
            return self._load_env_vars(parsed_args=parsed_args)
        else:
            return super().__call__()

    @overload
    def _load_env_vars(self) -> Mapping[str, str | None]: ...

    @overload
    def _load_env_vars(self, *, parsed_args: Namespace | SimpleNamespace | dict[str, Any]) -> CliSettingsSource[T]:
        """
        Loads the parsed command line arguments into the CLI environment settings variables.

        Note:
            The parsed args must be in `argparse.Namespace`, `SimpleNamespace`, or vars dictionary
            (e.g., vars(argparse.Namespace)) format.

        Args:
            parsed_args: The parsed args to load.

        Returns:
            CliSettingsSource: The object instance itself.
        """
        ...

    def _load_env_vars(
        self, *, parsed_args: Namespace | SimpleNamespace | dict[str, list[str] | str] | None = None
    ) -> Mapping[str, str | None] | CliSettingsSource[T]:
        if parsed_args is None:
            return {}

        if isinstance(parsed_args, (Namespace, SimpleNamespace)):
            parsed_args = vars(parsed_args)

        selected_subcommands = self._resolve_parsed_args(parsed_args)
        for arg_dest, arg_map in self._parser_map.items():
            if isinstance(arg_dest, str) and arg_dest.endswith(':subcommand'):
                for subcommand_dest in [arg.dest for arg in arg_map.values()]:
                    if subcommand_dest not in selected_subcommands:
                        parsed_args[subcommand_dest] = self.cli_parse_none_str

        parsed_args = {
            key: val
            for key, val in parsed_args.items()
            if not key.endswith(':subcommand') and val is not PydanticUndefined
        }
        if selected_subcommands:
            last_selected_subcommand = max(selected_subcommands, key=len)
            if not any(field_name for field_name in parsed_args.keys() if f'{last_selected_subcommand}.' in field_name):
                parsed_args[last_selected_subcommand] = '{}'

        parsed_args.update(self._cli_unknown_args)

        self.env_vars = parse_env_vars(
            cast(Mapping[str, str], parsed_args),
            self.case_sensitive,
            self.env_ignore_empty,
            self.cli_parse_none_str,
        )

        return self

    def _resolve_parsed_args(self, parsed_args: dict[str, list[str] | str]) -> list[str]:
        selected_subcommands: list[str] = []
        for field_name, val in list(parsed_args.items()):
            if isinstance(val, list):
                if self._is_nested_alias_path_only_workaround(parsed_args, field_name, val):
                    # Workaround for nested alias path environment variables not being handled.
                    # See https://github.com/pydantic/pydantic-settings/issues/670
                    continue

                cli_arg = self._parser_map.get(field_name, {}).get(None)
                if cli_arg and cli_arg.is_no_decode:
                    parsed_args[field_name] = ','.join(val)
                    continue

                parsed_args[field_name] = self._merge_parsed_list(val, field_name)
            elif field_name.endswith(':subcommand') and val is not None:
                selected_subcommands.append(self._parser_map[field_name][val].dest)
            elif self.cli_kebab_case == 'all':
                snake_val = val.replace('-', '_')
                cli_arg = self._parser_map.get(field_name, {}).get(None)
                if (
                    cli_arg
                    and cli_arg.field_info.annotation
                    and (snake_val in cli_arg.get_enum_names(cli_arg.field_info.annotation, False))
                ):
                    if '_' in val:
                        raise ValueError(f'Input should be kebab-case "{val.replace("_", "-")}", not "{val}"')
                    parsed_args[field_name] = snake_val

        return selected_subcommands

    def _is_nested_alias_path_only_workaround(
        self, parsed_args: dict[str, list[str] | str], field_name: str, val: list[str]
    ) -> bool:
        """
        Workaround for nested alias path environment variables not being handled.
        See https://github.com/pydantic/pydantic-settings/issues/670
        """
        known_arg = self._parser_map.get(field_name, {}).values()
        if not known_arg:
            return False
        arg = next(iter(known_arg))
        if arg.is_alias_path_only and arg.arg_prefix.endswith('.'):
            del parsed_args[field_name]
            nested_dest = arg.arg_prefix[:-1]
            nested_val = f'"{arg.preferred_alias}": {self._merge_parsed_list(val, field_name)}'
            parsed_args[nested_dest] = (
                f'{{{nested_val}}}'
                if nested_dest not in parsed_args
                else f'{parsed_args[nested_dest][:-1]}, {nested_val}}}'
            )
            return True
        return False

    def _get_merge_parsed_list_types(self, parsed_list: list[str], field_name: str) -> tuple[type | None, type | None]:
        merge_type = self._cli_dict_args.get(field_name, list)
        if (
            merge_type is list
            or not is_union_origin(get_origin(merge_type))
            or not any(
                type_
                for type_ in get_args(merge_type)
                if type_ is not type(None) and get_origin(type_) not in (dict, Mapping)
            )
        ):
            inferred_type = merge_type
        else:
            inferred_type = list if parsed_list and (len(parsed_list) > 1 or parsed_list[0].startswith('[')) else str

        return merge_type, inferred_type

    def _merged_list_to_str(self, merged_list: list[str], field_name: str) -> str:
        decode_list: list[str] = []
        is_use_decode: bool | None = None
        cli_arg_map = self._parser_map.get(field_name, {})
        for index, item in enumerate(merged_list):
            cli_arg = cli_arg_map.get(index)
            is_decode = cli_arg is None or not cli_arg.is_no_decode
            if is_use_decode is None:
                is_use_decode = is_decode
            elif is_use_decode != is_decode:
                raise SettingsError('Mixing Decode and NoDecode across different AliasPath fields is not allowed')
            if is_use_decode:
                item = item.replace('\\', '\\\\')
            elif item.startswith('"') and item.endswith('"'):
                item = item[1:-1]
            decode_list.append(item)
        merged_list_str = ','.join(decode_list)
        return f'[{merged_list_str}]' if is_use_decode else merged_list_str

    def _merge_parsed_list(self, parsed_list: list[str], field_name: str) -> str:
        try:
            merged_list: list[str] = []
            is_last_consumed_a_value = False
            merge_type, inferred_type = self._get_merge_parsed_list_types(parsed_list, field_name)
            for val in parsed_list:
                if not isinstance(val, str):
                    # If val is not a string, it's from an external parser and we can ignore parsing the rest of the
                    # list.
                    break
                val = val.strip()
                if val.startswith('[') and val.endswith(']'):
                    val = val[1:-1].strip()
                while val:
                    val = val.strip()
                    if val.startswith(','):
                        val = self._consume_comma(val, merged_list, is_last_consumed_a_value)
                        is_last_consumed_a_value = False
                    else:
                        if val.startswith('{') or val.startswith('['):
                            val = self._consume_object_or_array(val, merged_list)
                        else:
                            try:
                                val = self._consume_string_or_number(val, merged_list, merge_type)
                            except ValueError as e:
                                if merge_type is inferred_type:
                                    raise e
                                merge_type = inferred_type
                                val = self._consume_string_or_number(val, merged_list, merge_type)
                        is_last_consumed_a_value = True
                if not is_last_consumed_a_value:
                    val = self._consume_comma(val, merged_list, is_last_consumed_a_value)

            if merge_type is str:
                return merged_list[0]
            elif merge_type is list:
                return self._merged_list_to_str(merged_list, field_name)
            else:
                merged_dict: dict[str, str] = {}
                for item in merged_list:
                    merged_dict.update(json.loads(item))
                return json.dumps(merged_dict)
        except Exception as e:
            raise SettingsError(f'Parsing error encountered for {field_name}: {e}')

    def _consume_comma(self, item: str, merged_list: list[str], is_last_consumed_a_value: bool) -> str:
        if not is_last_consumed_a_value:
            merged_list.append('""')
        return item[1:]

    def _consume_object_or_array(self, item: str, merged_list: list[str]) -> str:
        count = 1
        close_delim = '}' if item.startswith('{') else ']'
        in_str = False
        for consumed in range(1, len(item)):
            if item[consumed] == '"' and item[consumed - 1] != '\\':
                in_str = not in_str
            elif in_str:
                continue
            elif item[consumed] in ('{', '['):
                count += 1
            elif item[consumed] in ('}', ']'):
                count -= 1
                if item[consumed] == close_delim and count == 0:
                    merged_list.append(item[: consumed + 1])
                    return item[consumed + 1 :]
        raise SettingsError(f'Missing end delimiter "{close_delim}"')

    def _consume_string_or_number(self, item: str, merged_list: list[str], merge_type: type[Any] | None) -> str:
        consumed = 0 if merge_type is not str else len(item)
        is_find_end_quote = False
        while consumed < len(item):
            if item[consumed] == '"' and (consumed == 0 or item[consumed - 1] != '\\'):
                is_find_end_quote = not is_find_end_quote
            if not is_find_end_quote and item[consumed] == ',':
                break
            consumed += 1
        if is_find_end_quote:
            raise SettingsError('Mismatched quotes')
        val_string = item[:consumed].strip()
        if merge_type in (list, str):
            try:
                float(val_string)
            except ValueError:
                if val_string == self.cli_parse_none_str:
                    val_string = 'null'
                if val_string not in ('true', 'false', 'null') and not val_string.startswith('"'):
                    val_string = f'"{val_string}"'
            merged_list.append(val_string)
        else:
            key, val = (kv for kv in val_string.split('=', 1))
            if key.startswith('"') and not key.endswith('"') and not val.startswith('"') and val.endswith('"'):
                raise ValueError(f'Dictionary key=val parameter is a quoted string: {val_string}')
            key, val = key.strip('"'), val.strip('"')
            merged_list.append(json.dumps({key: val}))
        return item[consumed:]

    def _verify_cli_flag_annotations(self, model: type[BaseModel], field_name: str, field_info: FieldInfo) -> None:
        if _CliImplicitFlag in field_info.metadata:
            cli_flag_name = 'CliImplicitFlag'
        elif _CliExplicitFlag in field_info.metadata:
            cli_flag_name = 'CliExplicitFlag'
        else:
            return

        if field_info.annotation is not bool:
            raise SettingsError(f'{cli_flag_name} argument {model.__name__}.{field_name} is not of type bool')

    def _sort_arg_fields(self, model: type[BaseModel]) -> list[tuple[str, FieldInfo]]:
        positional_variadic_arg = []
        positional_args, subcommand_args, optional_args = [], [], []
        for field_name, field_info in _get_model_fields(model).items():
            if _CliSubCommand in field_info.metadata:
                if not field_info.is_required():
                    raise SettingsError(f'subcommand argument {model.__name__}.{field_name} has a default value')
                else:
                    alias_names, *_ = _get_alias_names(field_name, field_info)
                    if len(alias_names) > 1:
                        raise SettingsError(f'subcommand argument {model.__name__}.{field_name} has multiple aliases')
                    field_types = [type_ for type_ in get_args(field_info.annotation) if type_ is not type(None)]
                    for field_type in field_types:
                        if not (is_model_class(field_type) or is_pydantic_dataclass(field_type)):
                            raise SettingsError(
                                f'subcommand argument {model.__name__}.{field_name} has type not derived from BaseModel'
                            )
                subcommand_args.append((field_name, field_info))
            elif _CliPositionalArg in field_info.metadata:
                alias_names, *_ = _get_alias_names(field_name, field_info)
                if len(alias_names) > 1:
                    raise SettingsError(f'positional argument {model.__name__}.{field_name} has multiple aliases')
                is_append_action = _annotation_contains_types(
                    field_info.annotation, (list, set, dict, Sequence, Mapping), is_strip_annotated=True
                )
                if not is_append_action:
                    positional_args.append((field_name, field_info))
                else:
                    positional_variadic_arg.append((field_name, field_info))
            else:
                self._verify_cli_flag_annotations(model, field_name, field_info)
                optional_args.append((field_name, field_info))

        if positional_variadic_arg:
            if len(positional_variadic_arg) > 1:
                field_names = ', '.join([name for name, info in positional_variadic_arg])
                raise SettingsError(f'{model.__name__} has multiple variadic positional arguments: {field_names}')
            elif subcommand_args:
                field_names = ', '.join([name for name, info in positional_variadic_arg + subcommand_args])
                raise SettingsError(
                    f'{model.__name__} has variadic positional arguments and subcommand arguments: {field_names}'
                )

        return positional_args + positional_variadic_arg + subcommand_args + optional_args

    @property
    def root_parser(self) -> T:
        """The connected root parser instance."""
        return self._root_parser

    def _connect_parser_method(
        self, parser_method: Callable[..., Any] | None, method_name: str, *args: Any, **kwargs: Any
    ) -> Callable[..., Any]:
        if (
            parser_method is not None
            and self.case_sensitive is False
            and method_name == 'parse_args_method'
            and isinstance(self._root_parser, _CliInternalArgParser)
        ):

            def parse_args_insensitive_method(
                root_parser: _CliInternalArgParser,
                args: list[str] | tuple[str, ...] | None = None,
                namespace: Namespace | None = None,
            ) -> Any:
                insensitive_args = []
                for arg in shlex.split(shlex.join(args)) if args else []:
                    flag_prefix = rf'\{self.cli_flag_prefix_char}{{1,2}}'
                    matched = re.match(rf'^({flag_prefix}[^\s=]+)(.*)', arg)
                    if matched:
                        arg = matched.group(1).lower() + matched.group(2)
                    insensitive_args.append(arg)
                return parser_method(root_parser, insensitive_args, namespace)

            return parse_args_insensitive_method

        elif parser_method is None:

            def none_parser_method(*args: Any, **kwargs: Any) -> Any:
                raise SettingsError(
                    f'cannot connect CLI settings source root parser: {method_name} is set to `None` but is needed for connecting'
                )

            return none_parser_method

        else:
            return parser_method

    def _connect_group_method(self, add_argument_group_method: Callable[..., Any] | None) -> Callable[..., Any]:
        add_argument_group = self._connect_parser_method(add_argument_group_method, 'add_argument_group_method')

        def add_group_method(parser: Any, **kwargs: Any) -> Any:
            if not kwargs.pop('_is_cli_mutually_exclusive_group'):
                kwargs.pop('required')
                return add_argument_group(parser, **kwargs)
            else:
                main_group_kwargs = {arg: kwargs.pop(arg) for arg in ['title', 'description'] if arg in kwargs}
                main_group_kwargs['title'] += ' (mutually exclusive)'
                group = add_argument_group(parser, **main_group_kwargs)
                if not hasattr(group, 'add_mutually_exclusive_group'):
                    raise SettingsError(
                        'cannot connect CLI settings source root parser: '
                        'group object is missing add_mutually_exclusive_group but is needed for connecting'
                    )
                return group.add_mutually_exclusive_group(**kwargs)

        return add_group_method

    def _connect_root_parser(
        self,
        root_parser: T,
        parse_args_method: Callable[..., Any] | None,
        add_argument_method: Callable[..., Any] | None = ArgumentParser.add_argument,
        add_argument_group_method: Callable[..., Any] | None = ArgumentParser.add_argument_group,
        add_parser_method: Callable[..., Any] | None = _SubParsersAction.add_parser,
        add_subparsers_method: Callable[..., Any] | None = ArgumentParser.add_subparsers,
        formatter_class: Any = RawDescriptionHelpFormatter,
    ) -> None:
        self._cli_unknown_args: dict[str, list[str]] = {}

        def _parse_known_args(*args: Any, **kwargs: Any) -> Namespace:
            args, unknown_args = ArgumentParser.parse_known_args(*args, **kwargs)
            for dest in self._cli_unknown_args:
                self._cli_unknown_args[dest] = unknown_args
            return cast(Namespace, args)

        self._root_parser = root_parser
        if parse_args_method is None:
            parse_args_method = _parse_known_args if self.cli_ignore_unknown_args else ArgumentParser.parse_args
        self._parse_args = self._connect_parser_method(parse_args_method, 'parse_args_method')
        self._add_argument = self._connect_parser_method(add_argument_method, 'add_argument_method')
        self._add_group = self._connect_group_method(add_argument_group_method)
        self._add_parser = self._connect_parser_method(add_parser_method, 'add_parser_method')
        self._add_subparsers = self._connect_parser_method(add_subparsers_method, 'add_subparsers_method')
        self._formatter_class = formatter_class
        self._cli_dict_args: dict[str, type[Any] | None] = {}
        self._parser_map: defaultdict[str | FieldInfo, dict[int | None | str, _CliArg]] = defaultdict(dict)
        self._add_parser_args(
            parser=self.root_parser,
            model=self.settings_cls,
            added_args=[],
            arg_prefix=self.env_prefix,
            subcommand_prefix=self.env_prefix,
            group=None,
            alias_prefixes=[],
            model_default=PydanticUndefined,
        )

    def _add_parser_args(
        self,
        parser: Any,
        model: type[BaseModel],
        added_args: list[str],
        arg_prefix: str,
        subcommand_prefix: str,
        group: Any,
        alias_prefixes: list[str],
        model_default: Any,
        is_model_suppressed: bool = False,
    ) -> ArgumentParser:
        subparsers: Any = None
        alias_path_args: dict[str, int | None] = {}
        # Ignore model default if the default is a model and not a subclass of the current model.
        model_default = (
            None
            if (
                (is_model_class(type(model_default)) or is_pydantic_dataclass(type(model_default)))
                and not issubclass(type(model_default), model)
            )
            else model_default
        )
        for field_name, field_info in self._sort_arg_fields(model):
            arg = _CliArg(
                field_info=field_info,
                parser_map=self._parser_map,
                model=model,
                field_name=field_name,
                arg_prefix=arg_prefix,
                case_sensitive=self.case_sensitive,
                hide_none_type=self.cli_hide_none_type,
                kebab_case=self.cli_kebab_case,
                enable_decoding=self.config.get('enable_decoding'),
                env_prefix_len=self.env_prefix_len,
            )
            alias_path_args.update(arg.alias_paths)

            if arg.subcommand_dest:
                for sub_model in arg.sub_models:
                    subcommand_alias = arg.subcommand_alias(sub_model)
                    subcommand_arg = self._parser_map[arg.subcommand_dest][subcommand_alias]
                    subcommand_arg.args = [subcommand_alias]
                    subcommand_arg.kwargs['allow_abbrev'] = False
                    subcommand_arg.kwargs['formatter_class'] = self._formatter_class
                    subcommand_arg.kwargs['description'] = (
                        None if sub_model.__doc__ is None else dedent(sub_model.__doc__)
                    )
                    subcommand_arg.kwargs['help'] = None if len(arg.sub_models) > 1 else field_info.description
                    if self.cli_use_class_docs_for_groups:
                        subcommand_arg.kwargs['help'] = None if sub_model.__doc__ is None else dedent(sub_model.__doc__)

                    subparsers = (
                        self._add_subparsers(
                            parser,
                            title='subcommands',
                            dest=f'{arg_prefix}:subcommand',
                            description=field_info.description if len(arg.sub_models) > 1 else None,
                        )
                        if subparsers is None
                        else subparsers
                    )

                    if hasattr(subparsers, 'metavar'):
                        subparsers.metavar = (
                            f'{subparsers.metavar[:-1]},{subcommand_alias}}}'
                            if subparsers.metavar
                            else f'{{{subcommand_alias}}}'
                        )

                    self._add_parser_args(
                        parser=self._add_parser(subparsers, *subcommand_arg.args, **subcommand_arg.kwargs),
                        model=sub_model,
                        added_args=[],
                        arg_prefix=f'{arg.dest}.',
                        subcommand_prefix=f'{subcommand_prefix}{arg.preferred_alias}.',
                        group=None,
                        alias_prefixes=[],
                        model_default=PydanticUndefined,
                    )
            else:
                flag_prefix: str = self._cli_flag_prefix
                arg.kwargs['dest'] = arg.dest
                arg.kwargs['default'] = CLI_SUPPRESS
                arg.kwargs['help'] = self._help_format(field_name, field_info, model_default, is_model_suppressed)
                arg.kwargs['metavar'] = self._metavar_format(field_info.annotation)
                arg.kwargs['required'] = (
                    self.cli_enforce_required and field_info.is_required() and model_default is PydanticUndefined
                )

                arg_names = self._get_arg_names(
                    arg_prefix, subcommand_prefix, alias_prefixes, arg.alias_names, added_args
                )
                if not arg_names or (arg.kwargs['dest'] in added_args):
                    continue

                self._convert_append_action(arg.kwargs, field_info, arg.is_append_action)

                if _CliPositionalArg in field_info.metadata:
                    arg_names, flag_prefix = self._convert_positional_arg(
                        arg.kwargs, field_info, arg.preferred_alias, model_default
                    )

                self._convert_bool_flag(arg.kwargs, field_info, model_default)

                if arg.is_parser_submodel and not getattr(field_info.annotation, '__pydantic_root_model__', False):
                    self._add_parser_submodels(
                        parser,
                        model,
                        arg.sub_models,
                        added_args,
                        arg_prefix,
                        subcommand_prefix,
                        flag_prefix,
                        arg_names,
                        arg.kwargs,
                        field_name,
                        field_info,
                        arg.alias_names,
                        model_default=model_default,
                        is_model_suppressed=is_model_suppressed,
                    )
                elif _CliUnknownArgs in field_info.metadata:
                    self._cli_unknown_args[arg.kwargs['dest']] = []
                elif not arg.is_alias_path_only:
                    if isinstance(group, dict):
                        group = self._add_group(parser, **group)
                    context = parser if group is None else group
                    arg.args = [f'{flag_prefix[: len(name)]}{name}' for name in arg_names]
                    self._add_argument(context, *arg.args, **arg.kwargs)
                    added_args += list(arg_names)

        self._add_parser_alias_paths(parser, alias_path_args, added_args, arg_prefix, subcommand_prefix, group)
        return parser

    def _convert_append_action(self, kwargs: dict[str, Any], field_info: FieldInfo, is_append_action: bool) -> None:
        if is_append_action:
            kwargs['action'] = 'append'
            if _annotation_contains_types(field_info.annotation, (dict, Mapping), is_strip_annotated=True):
                self._cli_dict_args[kwargs['dest']] = field_info.annotation

    def _convert_bool_flag(self, kwargs: dict[str, Any], field_info: FieldInfo, model_default: Any) -> None:
        if kwargs['metavar'] == 'bool':
            if (self.cli_implicit_flags or _CliImplicitFlag in field_info.metadata) and (
                _CliExplicitFlag not in field_info.metadata
            ):
                del kwargs['metavar']
                kwargs['action'] = BooleanOptionalAction

    def _convert_positional_arg(
        self, kwargs: dict[str, Any], field_info: FieldInfo, preferred_alias: str, model_default: Any
    ) -> tuple[list[str], str]:
        flag_prefix = ''
        arg_names = [kwargs['dest']]
        kwargs['default'] = PydanticUndefined
        kwargs['metavar'] = _CliArg.get_kebab_case(preferred_alias.upper(), self.cli_kebab_case)

        # Note: CLI positional args are always strictly required at the CLI. Therefore, use field_info.is_required in
        # conjunction with model_default instead of the derived kwargs['required'].
        is_required = field_info.is_required() and model_default is PydanticUndefined
        if kwargs.get('action') == 'append':
            del kwargs['action']
            kwargs['nargs'] = '+' if is_required else '*'
        elif not is_required:
            kwargs['nargs'] = '?'

        del kwargs['dest']
        del kwargs['required']
        return arg_names, flag_prefix

    def _get_arg_names(
        self,
        arg_prefix: str,
        subcommand_prefix: str,
        alias_prefixes: list[str],
        alias_names: tuple[str, ...],
        added_args: list[str],
    ) -> list[str]:
        arg_names: list[str] = []
        for prefix in [arg_prefix] + alias_prefixes:
            for name in alias_names:
                arg_name = _CliArg.get_kebab_case(
                    f'{prefix}{name}'
                    if subcommand_prefix == self.env_prefix
                    else f'{prefix.replace(subcommand_prefix, "", 1)}{name}',
                    self.cli_kebab_case,
                )
                if arg_name not in added_args:
                    arg_names.append(arg_name)

        if self.cli_shortcuts:
            for target, aliases in self.cli_shortcuts.items():
                if target in arg_names:
                    alias_list = [aliases] if isinstance(aliases, str) else aliases
                    arg_names.extend(alias for alias in alias_list if alias not in added_args)

        return arg_names

    def _add_parser_submodels(
        self,
        parser: Any,
        model: type[BaseModel],
        sub_models: list[type[BaseModel]],
        added_args: list[str],
        arg_prefix: str,
        subcommand_prefix: str,
        flag_prefix: str,
        arg_names: list[str],
        kwargs: dict[str, Any],
        field_name: str,
        field_info: FieldInfo,
        alias_names: tuple[str, ...],
        model_default: Any,
        is_model_suppressed: bool,
    ) -> None:
        if issubclass(model, CliMutuallyExclusiveGroup):
            # Argparse has deprecated "calling add_argument_group() or add_mutually_exclusive_group() on a
            # mutually exclusive group" (https://docs.python.org/3/library/argparse.html#mutual-exclusion).
            # Since nested models result in a group add, raise an exception for nested models in a mutually
            # exclusive group.
            raise SettingsError('cannot have nested models in a CliMutuallyExclusiveGroup')

        model_group: Any = None
        model_group_kwargs: dict[str, Any] = {}
        model_group_kwargs['title'] = f'{arg_names[0]} options'
        model_group_kwargs['description'] = field_info.description
        model_group_kwargs['required'] = kwargs['required']
        model_group_kwargs['_is_cli_mutually_exclusive_group'] = any(
            issubclass(model, CliMutuallyExclusiveGroup) for model in sub_models
        )
        if model_group_kwargs['_is_cli_mutually_exclusive_group'] and len(sub_models) > 1:
            raise SettingsError('cannot use union with CliMutuallyExclusiveGroup')
        if self.cli_use_class_docs_for_groups and len(sub_models) == 1:
            model_group_kwargs['description'] = None if sub_models[0].__doc__ is None else dedent(sub_models[0].__doc__)

        if model_default is not PydanticUndefined:
            if is_model_class(type(model_default)) or is_pydantic_dataclass(type(model_default)):
                model_default = getattr(model_default, field_name)
        else:
            if field_info.default is not PydanticUndefined:
                model_default = field_info.default
            elif field_info.default_factory is not None:
                model_default = field_info.default_factory
        if model_default is None:
            desc_header = f'default: {self.cli_parse_none_str} (undefined)'
            if model_group_kwargs['description'] is not None:
                model_group_kwargs['description'] = dedent(f'{desc_header}\n{model_group_kwargs["description"]}')
            else:
                model_group_kwargs['description'] = desc_header

        preferred_alias = alias_names[0]
        is_model_suppressed = self._is_field_suppressed(field_info) or is_model_suppressed
        if is_model_suppressed:
            model_group_kwargs['description'] = CLI_SUPPRESS
        if not self.cli_avoid_json:
            added_args.append(arg_names[0])
            kwargs['required'] = False
            kwargs['nargs'] = '?'
            kwargs['const'] = '{}'
            kwargs['help'] = (
                CLI_SUPPRESS if is_model_suppressed else f'set {arg_names[0]} from JSON string (default: {{}})'
            )
            model_group = self._add_group(parser, **model_group_kwargs)
            self._add_argument(model_group, *(f'{flag_prefix}{name}' for name in arg_names), **kwargs)
        for model in sub_models:
            self._add_parser_args(
                parser=parser,
                model=model,
                added_args=added_args,
                arg_prefix=f'{arg_prefix}{preferred_alias}.',
                subcommand_prefix=subcommand_prefix,
                group=model_group if model_group else model_group_kwargs,
                alias_prefixes=[f'{arg_prefix}{name}.' for name in alias_names[1:]],
                model_default=model_default,
                is_model_suppressed=is_model_suppressed,
            )

    def _add_parser_alias_paths(
        self,
        parser: Any,
        alias_path_args: dict[str, int | None],
        added_args: list[str],
        arg_prefix: str,
        subcommand_prefix: str,
        group: Any,
    ) -> None:
        if alias_path_args:
            context = parser
            if group is not None:
                context = self._add_group(parser, **group) if isinstance(group, dict) else group
            for name, index in alias_path_args.items():
                arg_name = (
                    f'{arg_prefix}{name}'
                    if subcommand_prefix == self.env_prefix
                    else f'{arg_prefix.replace(subcommand_prefix, "", 1)}{name}'
                )
                kwargs: dict[str, Any] = {}
                kwargs['default'] = CLI_SUPPRESS
                kwargs['help'] = 'pydantic alias path'
                kwargs['action'] = 'append'
                kwargs['metavar'] = 'list'
                if index is None:
                    kwargs['metavar'] = 'dict'
                    self._cli_dict_args[arg_name] = dict
                args = [f'{self._cli_flag_prefix}{arg_name}']
                for key, arg in self._parser_map[arg_name].items():
                    arg.args, arg.kwargs = args, kwargs
                self._add_argument(context, *args, **kwargs)
                added_args.append(arg_name)

    def _get_modified_args(self, obj: Any) -> tuple[str, ...]:
        if not self.cli_hide_none_type:
            return get_args(obj)
        else:
            return tuple([type_ for type_ in get_args(obj) if type_ is not type(None)])

    def _metavar_format_choices(self, args: list[str], obj_qualname: str | None = None) -> str:
        if 'JSON' in args:
            args = args[: args.index('JSON') + 1] + [arg for arg in args[args.index('JSON') + 1 :] if arg != 'JSON']
        metavar = ','.join(args)
        if obj_qualname:
            return f'{obj_qualname}[{metavar}]'
        else:
            return metavar if len(args) == 1 else f'{{{metavar}}}'

    def _metavar_format_recurse(self, obj: Any) -> str:
        """Pretty metavar representation of a type. Adapts logic from `pydantic._repr.display_as_type`."""
        obj = _strip_annotated(obj)
        if _is_function(obj):
            # If function is locally defined use __name__ instead of __qualname__
            return obj.__name__ if '<locals>' in obj.__qualname__ else obj.__qualname__
        elif obj is ...:
            return '...'
        elif isinstance(obj, Representation):
            return repr(obj)
        elif typing_objects.is_typealiastype(obj):
            return str(obj)

        origin = get_origin(obj)
        if origin is None and not isinstance(obj, (type, typing.ForwardRef, typing_extensions.ForwardRef)):
            obj = obj.__class__

        if is_union_origin(origin):
            return self._metavar_format_choices(list(map(self._metavar_format_recurse, self._get_modified_args(obj))))
        elif typing_objects.is_literal(origin):
            return self._metavar_format_choices(list(map(str, self._get_modified_args(obj))))
        elif _lenient_issubclass(obj, Enum):
            return self._metavar_format_choices(
                [_CliArg.get_kebab_case(val.name, self.cli_kebab_case == 'all') for val in obj]
            )
        elif isinstance(obj, _WithArgsTypes):
            return self._metavar_format_choices(
                list(map(self._metavar_format_recurse, self._get_modified_args(obj))),
                obj_qualname=obj.__qualname__ if hasattr(obj, '__qualname__') else str(obj),
            )
        elif obj is type(None):
            return self.cli_parse_none_str
        elif is_model_class(obj) or is_pydantic_dataclass(obj):
            return (
                self._metavar_format_recurse(_get_model_fields(obj)['root'].annotation)
                if getattr(obj, '__pydantic_root_model__', False)
                else 'JSON'
            )
        elif isinstance(obj, type):
            return obj.__qualname__
        else:
            return repr(obj).replace('typing.', '').replace('typing_extensions.', '')

    def _metavar_format(self, obj: Any) -> str:
        return self._metavar_format_recurse(obj).replace(', ', ',')

    def _help_format(
        self, field_name: str, field_info: FieldInfo, model_default: Any, is_model_suppressed: bool
    ) -> str:
        _help = field_info.description if field_info.description else ''
        if is_model_suppressed or self._is_field_suppressed(field_info):
            return CLI_SUPPRESS

        if field_info.is_required() and model_default in (PydanticUndefined, None):
            if _CliPositionalArg not in field_info.metadata:
                ifdef = 'ifdef: ' if model_default is None else ''
                _help += f' ({ifdef}required)' if _help else f'({ifdef}required)'
        else:
            default = f'(default: {self.cli_parse_none_str})'
            if is_model_class(type(model_default)) or is_pydantic_dataclass(type(model_default)):
                default = f'(default: {getattr(model_default, field_name)})'
            elif model_default not in (PydanticUndefined, None) and _is_function(model_default):
                default = f'(default factory: {self._metavar_format(model_default)})'
            elif field_info.default not in (PydanticUndefined, None):
                enum_name = _annotation_enum_val_to_name(field_info.annotation, field_info.default)
                default = f'(default: {field_info.default if enum_name is None else enum_name})'
            elif field_info.default_factory is not None:
                default = f'(default factory: {self._metavar_format(field_info.default_factory)})'
            _help += f' {default}' if _help else default
        return _help.replace('%', '%%') if issubclass(type(self._root_parser), ArgumentParser) else _help

    def _is_field_suppressed(self, field_info: FieldInfo) -> bool:
        _help = field_info.description if field_info.description else ''
        return _help == CLI_SUPPRESS or CLI_SUPPRESS in field_info.metadata

    def _update_alias_path_only_default(
        self, arg_name: str, value: Any, field_info: FieldInfo, alias_path_only_defaults: dict[str, Any]
    ) -> list[Any] | dict[str, Any]:
        alias_path: AliasPath = [
            alias if isinstance(alias, AliasPath) else cast(AliasPath, alias.choices[0])
            for alias in (field_info.alias, field_info.validation_alias)
            if isinstance(alias, (AliasPath, AliasChoices))
        ][0]

        alias_nested_paths: list[str] = alias_path.path[1:-1]  # type: ignore
        if not alias_nested_paths:
            alias_path_only_defaults.setdefault(arg_name, [])
            alias_default = alias_path_only_defaults[arg_name]
        else:
            alias_path_only_defaults.setdefault(arg_name, {})
            current_path = alias_path_only_defaults[arg_name]

            for nested_path in alias_nested_paths[:-1]:
                current_path.setdefault(nested_path, {})
                current_path = current_path[nested_path]
            current_path.setdefault(alias_nested_paths[-1], [])
            alias_default = current_path[alias_nested_paths[-1]]

        alias_path_index = cast(int, alias_path.path[-1])
        alias_default.extend([''] * max(alias_path_index + 1 - len(alias_default), 0))
        alias_default[alias_path_index] = value
        return alias_path_only_defaults[arg_name]

    def _serialized_args(self, model: PydanticModel, _is_submodel: bool = False) -> list[str]:
        alias_path_only_defaults: dict[str, Any] = {}
        optional_args: list[str | list[Any] | dict[str, Any]] = []
        positional_args: list[str | list[Any] | dict[str, Any]] = []
        subcommand_args: list[str] = []
        for field_name, field_info in _get_model_fields(type(model) if _is_submodel else self.settings_cls).items():
            model_default = getattr(model, field_name)
            if field_info.default == model_default:
                continue
            if _CliSubCommand in field_info.metadata and model_default is None:
                continue
            arg = next(iter(self._parser_map[field_info].values()))
            if arg.subcommand_dest:
                subcommand_args.append(arg.subcommand_alias(type(model_default)))
                subcommand_args += self._serialized_args(model_default, _is_submodel=True)
                continue
            if is_model_class(type(model_default)) or is_pydantic_dataclass(type(model_default)):
                positional_args += self._serialized_args(model_default, _is_submodel=True)
                continue

            matched = re.match(r'(-*)(.+)', arg.preferred_arg_name)
            flag_chars, arg_name = matched.groups() if matched else ('', '')
            value: str | list[Any] | dict[str, Any] = (
                json.dumps(model_default) if isinstance(model_default, (dict, list, set)) else str(model_default)
            )

            if arg.is_alias_path_only:
                # For alias path only, we wont know the complete value until we've finished parsing the entire class. In
                # this case, insert value as a non-string reference pointing to the relevant alias_path_only_defaults
                # entry and convert into completed string value later.
                value = self._update_alias_path_only_default(arg_name, value, field_info, alias_path_only_defaults)

            if _CliPositionalArg in field_info.metadata:
                for value in model_default if isinstance(model_default, list) else [model_default]:
                    value = json.dumps(value) if isinstance(value, (dict, list, set)) else str(value)
                    positional_args.append(value)
                continue

            # Note: prepend 'no-' for boolean optional action flag if model_default value is False and flag is not a short option
            if arg.kwargs.get('action') == BooleanOptionalAction and model_default is False and flag_chars == '--':
                flag_chars += 'no-'

            optional_args.append(f'{flag_chars}{arg_name}')

            # If implicit bool flag, do not add a value
            if arg.kwargs.get('action') != BooleanOptionalAction:
                optional_args.append(value)

        serialized_args: list[str] = []
        serialized_args += [json.dumps(value) if not isinstance(value, str) else value for value in optional_args]
        serialized_args += [json.dumps(value) if not isinstance(value, str) else value for value in positional_args]
        return serialized_args + subcommand_args
