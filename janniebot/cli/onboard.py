"""Interactive onboarding questionnaire for janniebot."""

import json
import types
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, NamedTuple, get_args, get_origin

questionary: types.ModuleType | None
try:
    import questionary as _questionary_impl
    questionary = _questionary_impl
except ModuleNotFoundError:  # pragma: no cover - exercised in environments without wizard deps
    questionary = None
from loguru import logger
from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from janniebot.cli.models import (
    format_token_count,
    get_model_context_limit,
    get_model_suggestions,
)
from janniebot.config.loader import get_config_path, load_config
from janniebot.config.schema import Config

console = Console()


@dataclass
class OnboardResult:
    """Result of an onboarding session."""

    config: Config
    should_save: bool

# --- Field Hints for Select Fields ---
# Maps field names to (choices, hint_text)
# To add a new select field with hints, add an entry:
#   "field_name": (["choice1", "choice2", ...], "hint text for the field")
_SELECT_FIELD_HINTS: dict[str, tuple[list[str], str]] = {
    "reasoning_effort": (
        ["low", "medium", "high"],
        "low / medium / high - enables LLM thinking mode",
    ),
}

# --- Key Bindings for Navigation ---

_BACK_PRESSED = object()  # Sentinel value for back navigation


def _get_questionary():
    """Return questionary or raise a clear error when wizard deps are unavailable."""
    if questionary is None:
        raise RuntimeError(
            "Interactive onboarding requires the optional 'questionary' dependency. "
            "Install project dependencies and rerun with --wizard."
        )
    return questionary


def _select_with_back(
    prompt: str, choices: list[str], default: str | None = None
) -> str | None | object:
    """Select with Escape/Left arrow support for going back.

    Args:
        prompt: The prompt text to display.
        choices: List of choices to select from. Must not be empty.
        default: The default choice to pre-select. If not in choices, first item is used.

    Returns:
        _BACK_PRESSED sentinel if user pressed Escape or Left arrow
        The selected choice string if user confirmed
        None if user cancelled (Ctrl+C)
    """
    from prompt_toolkit.application import Application as PTApplication
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    # Validate choices
    if not choices:
        logger.warning("Empty choices list provided to _select_with_back")
        return None

    # Find default index
    selected_index = 0
    if default and default in choices:
        selected_index = choices.index(default)

    # State holder for the result
    state: dict[str, str | None | object] = {"result": None}

    # Build menu items (uses closure over selected_index)
    def get_menu_text():
        items = []
        for i, choice in enumerate(choices):
            if i == selected_index:
                items.append(("class:selected", f"> {choice}\n"))
            else:
                items.append(("", f"  {choice}\n"))
        return items

    # Create layout
    menu_control = FormattedTextControl(get_menu_text)
    menu_window = Window(content=menu_control, height=len(choices))

    prompt_control = FormattedTextControl(lambda: [("class:question", f"> {prompt}")])
    prompt_window = Window(content=prompt_control, height=1)

    layout = Layout(HSplit([prompt_window, menu_window]))

    # Key bindings
    bindings = KeyBindings()

    @bindings.add(Keys.Up)
    def _up(event):
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(choices)
        event.app.invalidate()

    @bindings.add(Keys.Down)
    def _down(event):
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(choices)
        event.app.invalidate()

    @bindings.add(Keys.Enter)
    def _enter(event):
        state["result"] = choices[selected_index]
        event.app.exit()

    @bindings.add("escape")
    def _escape(event):
        state["result"] = _BACK_PRESSED
        event.app.exit()

    @bindings.add(Keys.Left)
    def _left(event):
        state["result"] = _BACK_PRESSED
        event.app.exit()

    @bindings.add(Keys.ControlC)
    def _ctrl_c(event):
        state["result"] = None
        event.app.exit()

    # Style
    style = Style.from_dict({
        "selected": "fg:green bold",
        "question": "fg:cyan",
    })

    app: PTApplication = PTApplication(layout=layout, key_bindings=bindings, style=style)
    try:
        app.run()
    except Exception:
        logger.exception("Error in select prompt")
        return None

    return state["result"]

# --- Type Introspection ---


class FieldTypeInfo(NamedTuple):
    """Result of field type introspection."""

    type_name: str
    inner_type: Any


def _get_field_type_info(field_info) -> FieldTypeInfo:
    """Extract field type info from Pydantic field."""
    annotation = field_info.annotation
    if annotation is None:
        return FieldTypeInfo("str", None)

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is types.UnionType:
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            annotation = non_none_args[0]
            origin = get_origin(annotation)
            args = get_args(annotation)

    _simple_types: dict[type, str] = {bool: "bool", int: "int", float: "float"}

    if origin is list or (hasattr(origin, "__name__") and origin.__name__ == "List"):
        return FieldTypeInfo("list", args[0] if args else str)
    if origin is dict or (hasattr(origin, "__name__") and origin.__name__ == "Dict"):
        return FieldTypeInfo("dict", None)
    for py_type, name in _simple_types.items():
        if annotation is py_type:
            return FieldTypeInfo(name, None)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return FieldTypeInfo("model", annotation)
    return FieldTypeInfo("str", None)


def _get_field_display_name(field_key: str, field_info) -> str:
    """Get display name for a field."""
    if field_info and field_info.description:
        return field_info.description
    name = field_key
    suffix_map = {
        "_s": " (seconds)",
        "_ms": " (ms)",
        "_url": " URL",
        "_path": " Path",
        "_id": " ID",
        "_key": " Key",
        "_token": " Token",
    }
    for suffix, replacement in suffix_map.items():
        if name.endswith(suffix):
            name = name[: -len(suffix)] + replacement
            break
    return name.replace("_", " ").title()


# --- Sensitive Field Masking ---

_SENSITIVE_KEYWORDS = frozenset({"api_key", "token", "secret", "password", "credentials"})


def _is_sensitive_field(field_name: str) -> bool:
    """Check if a field name indicates sensitive content."""
    return any(kw in field_name.lower() for kw in _SENSITIVE_KEYWORDS)


def _mask_value(value: str) -> str:
    """Mask a sensitive value, showing only the last 4 characters."""
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


# --- Value Formatting ---


def _format_value(value: Any, rich: bool = True, field_name: str = "") -> str:
    """Single recursive entry point for safe value display. Handles any depth."""
    if value is None or value == "" or value == {} or value == []:
        return "[dim]not set[/dim]" if rich else "[not set]"
    if _is_sensitive_field(field_name) and isinstance(value, str):
        masked = _mask_value(value)
        return f"[dim]{masked}[/dim]" if rich else masked
    if isinstance(value, BaseModel):
        parts = []
        for fname, _finfo in type(value).model_fields.items():
            fval = getattr(value, fname, None)
            formatted = _format_value(fval, rich=False, field_name=fname)
            if formatted != "[not set]":
                parts.append(f"{fname}={formatted}")
        return ", ".join(parts) if parts else ("[dim]not set[/dim]" if rich else "[not set]")
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


def _format_value_for_input(value: Any, field_type: str) -> str:
    """Format a value for use as input default."""
    if value is None or value == "":
        return ""
    if field_type == "list" and isinstance(value, list):
        return ",".join(str(v) for v in value)
    if field_type == "dict" and isinstance(value, dict):
        return json.dumps(value)
    return str(value)


# --- Rich UI Components ---


def _show_config_panel(display_name: str, model: BaseModel, fields: list) -> None:
    """Display current configuration as a rich table."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    for fname, field_info in fields:
        value = getattr(model, fname, None)
        display = _get_field_display_name(fname, field_info)
        formatted = _format_value(value, rich=True, field_name=fname)
        table.add_row(display, formatted)

    console.print(Panel(table, title=f"[bold]{display_name}[/bold]", border_style="blue"))


def _show_main_menu_header() -> None:
    """Display the main menu header."""
    from janniebot import __logo__, __version__

    console.print()
    # Use Align.CENTER for the single line of text
    from rich.align import Align

    console.print(
        Align.center(f"{__logo__} [bold cyan]janniebot[{__version__}][/bold cyan]")
    )
    console.print()


def _show_section_header(title: str, subtitle: str = "") -> None:
    """Display a section header."""
    console.print()
    if subtitle:
        console.print(
            Panel(f"[dim]{subtitle}[/dim]", title=f"[bold]{title}[/bold]", border_style="blue")
        )
    else:
        console.print(Panel("", title=f"[bold]{title}[/bold]", border_style="blue"))


# --- Input Handlers ---


def _input_bool(display_name: str, current: bool | None) -> bool | None:
    """Get boolean input via confirm dialog."""
    return _get_questionary().confirm(
        display_name,
        default=bool(current) if current is not None else False,
    ).ask()


def _input_text(display_name: str, current: Any, field_type: str) -> Any:
    """Get text input and parse based on field type."""
    default = _format_value_for_input(current, field_type)

    value = _get_questionary().text(f"{display_name}:", default=default).ask()

    if value is None or value == "":
        return None

    if field_type == "int":
        try:
            return int(value)
        except ValueError:
            console.print("[yellow]! Invalid number format, value not saved[/yellow]")
            return None
    elif field_type == "float":
        try:
            return float(value)
        except ValueError:
            console.print("[yellow]! Invalid number format, value not saved[/yellow]")
            return None
    elif field_type == "list":
        return [v.strip() for v in value.split(",") if v.strip()]
    elif field_type == "dict":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            console.print("[yellow]! Invalid JSON format, value not saved[/yellow]")
            return None

    return value


def _input_with_existing(
    display_name: str, current: Any, field_type: str
) -> Any:
    """Handle input with 'keep existing' option for non-empty values."""
    has_existing = current is not None and current != "" and current != {} and current != []

    if has_existing and not isinstance(current, list):
        choice = _get_questionary().select(
            display_name,
            choices=["Enter new value", "Keep existing value"],
            default="Keep existing value",
        ).ask()
        if choice == "Keep existing value" or choice is None:
            return None

    return _input_text(display_name, current, field_type)


# --- Pydantic Model Configuration ---


def _get_current_provider(model: BaseModel) -> str:
    """Get the current provider setting from a model (if available)."""
    if hasattr(model, "provider"):
        return getattr(model, "provider", "auto") or "auto"
    return "auto"


def _input_model_with_autocomplete(
    display_name: str, current: Any, provider: str
) -> str | None:
    """Get model input with autocomplete suggestions.

    """
    from prompt_toolkit.completion import Completer, Completion

    default = str(current) if current else ""

    class DynamicModelCompleter(Completer):
        """Completer that dynamically fetches model suggestions."""

        def __init__(self, provider_name: str):
            self.provider = provider_name

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            suggestions = get_model_suggestions(text, provider=self.provider, limit=50)
            for model in suggestions:
                # Skip if model doesn't contain the typed text
                if text.lower() not in model.lower():
                    continue
                yield Completion(
                    model,
                    start_position=-len(text),
                    display=model,
                )

    value = _get_questionary().autocomplete(
        f"{display_name}:",
        choices=[""],  # Placeholder, actual completions from completer
        completer=DynamicModelCompleter(provider),
        default=default,
        qmark=">",
    ).ask()

    return value if value else None


def _input_context_window_with_recommendation(
    display_name: str, current: Any, model_obj: BaseModel
) -> int | None:
    """Get context window input with option to fetch recommended value."""
    current_val = current if current else ""

    choices = ["Enter new value"]
    if current_val:
        choices.append("Keep existing value")
    choices.append("[?] Get recommended value")

    choice = _get_questionary().select(
        display_name,
        choices=choices,
        default="Enter new value",
    ).ask()

    if choice is None:
        return None

    if choice == "Keep existing value":
        return None

    if choice == "[?] Get recommended value":
        # Get the model name from the model object
        model_name = getattr(model_obj, "model", None)
        if not model_name:
            console.print("[yellow]! Please configure the model field first[/yellow]")
            return None

        provider = _get_current_provider(model_obj)
        context_limit = get_model_context_limit(model_name, provider)

        if context_limit:
            console.print(f"[green]+ Recommended context window: {format_token_count(context_limit)} tokens[/green]")
            return context_limit
        else:
            console.print("[yellow]! Could not fetch model info, please enter manually[/yellow]")
            # Fall through to manual input

    # Manual input
    value = _get_questionary().text(
        f"{display_name}:",
        default=str(current_val) if current_val else "",
    ).ask()

    if value is None or value == "":
        return None

    try:
        return int(value)
    except ValueError:
        console.print("[yellow]! Invalid number format, value not saved[/yellow]")
        return None


def _handle_model_field(
    working_model: BaseModel, field_name: str, field_display: str, current_value: Any
) -> None:
    """Handle the 'model' field with autocomplete and context-window auto-fill."""
    provider = _get_current_provider(working_model)
    new_value = _input_model_with_autocomplete(field_display, current_value, provider)
    if new_value is not None and new_value != current_value:
        setattr(working_model, field_name, new_value)
        _try_auto_fill_context_window(working_model, new_value)


def _handle_context_window_field(
    working_model: BaseModel, field_name: str, field_display: str, current_value: Any
) -> None:
    """Handle context_window_tokens with recommendation lookup."""
    new_value = _input_context_window_with_recommendation(
        field_display, current_value, working_model
    )
    if new_value is not None:
        setattr(working_model, field_name, new_value)


_FIELD_HANDLERS: dict[str, Any] = {
    "model": _handle_model_field,
    "context_window_tokens": _handle_context_window_field,
}


def _configure_pydantic_model(
    model: BaseModel,
    display_name: str,
    *,
    skip_fields: set[str] | None = None,
) -> BaseModel | None:
    """Configure a Pydantic model interactively.

    Returns the updated model only when the user explicitly selects "Done".
    Back and cancel actions discard the section draft.
    """
    skip_fields = skip_fields or set()
    working_model = model.model_copy(deep=True)

    fields = [
        (name, info)
        for name, info in type(working_model).model_fields.items()
        if name not in skip_fields
    ]
    if not fields:
        console.print(f"[dim]{display_name}: No configurable fields[/dim]")
        return working_model

    def get_choices() -> list[str]:
        items = []
        for fname, finfo in fields:
            value = getattr(working_model, fname, None)
            display = _get_field_display_name(fname, finfo)
            formatted = _format_value(value, rich=False, field_name=fname)
            items.append(f"{display}: {formatted}")
        return items + ["[Done]"]

    while True:
        console.clear()
        _show_config_panel(display_name, working_model, fields)
        choices = get_choices()
        answer = _select_with_back("Select field to configure:", choices)

        if answer is _BACK_PRESSED or answer is None:
            return None
        if answer == "[Done]":
            return working_model

        field_idx = next((i for i, c in enumerate(choices) if c == answer), -1)
        if field_idx < 0 or field_idx >= len(fields):
            return None

        field_name, field_info = fields[field_idx]
        current_value = getattr(working_model, field_name, None)
        ftype = _get_field_type_info(field_info)
        field_display = _get_field_display_name(field_name, field_info)

        # Nested Pydantic model - recurse
        if ftype.type_name == "model":
            nested = current_value
            created = nested is None
            if nested is None and ftype.inner_type:
                nested = ftype.inner_type()
            if nested and isinstance(nested, BaseModel):
                updated = _configure_pydantic_model(nested, field_display)
                if updated is not None:
                    setattr(working_model, field_name, updated)
                elif created:
                    setattr(working_model, field_name, None)
            continue

        # Registered special-field handlers
        handler = _FIELD_HANDLERS.get(field_name)
        if handler:
            handler(working_model, field_name, field_display, current_value)
            continue

        # Select fields with hints (e.g. reasoning_effort)
        if field_name in _SELECT_FIELD_HINTS:
            choices_list, hint = _SELECT_FIELD_HINTS[field_name]
            select_choices = choices_list + ["(clear/unset)"]
            console.print(f"[dim]  Hint: {hint}[/dim]")
            new_value = _select_with_back(
                field_display, select_choices, default=current_value or select_choices[0]
            )
            if new_value is _BACK_PRESSED:
                continue
            if new_value == "(clear/unset)":
                setattr(working_model, field_name, None)
            elif new_value is not None:
                setattr(working_model, field_name, new_value)
            continue

        # Generic field input
        if ftype.type_name == "bool":
            new_value = _input_bool(field_display, current_value)
        else:
            new_value = _input_with_existing(field_display, current_value, ftype.type_name)
        if new_value is not None:
            setattr(working_model, field_name, new_value)


def _try_auto_fill_context_window(model: BaseModel, new_model_name: str) -> None:
    """Try to auto-fill context_window_tokens if it's at default value.

    Note:
        This function imports AgentDefaults from janniebot.config.schema to get
        the default context_window_tokens value. If the schema changes, this
        coupling needs to be updated accordingly.
    """
    # Check if context_window_tokens field exists
    if not hasattr(model, "context_window_tokens"):
        return

    current_context = getattr(model, "context_window_tokens", None)

    # Check if current value is the default (65536)
    # We only auto-fill if the user hasn't changed it from default
    from janniebot.config.schema import AgentDefaults

    default_context = AgentDefaults.model_fields["context_window_tokens"].default

    if current_context != default_context:
        return  # User has customized it, don't override

    provider = _get_current_provider(model)
    context_limit = get_model_context_limit(new_model_name, provider)

    if context_limit:
        setattr(model, "context_window_tokens", context_limit)
        console.print(f"[green]+ Auto-filled context window: {format_token_count(context_limit)} tokens[/green]")
    else:
        console.print("[dim](i) Could not auto-fill context window (model not in database)[/dim]")


# --- Provider Configuration ---


@lru_cache(maxsize=1)
def _get_provider_info() -> dict[str, tuple[str, bool, bool, str]]:
    """Get provider info from registry (cached)."""
    from janniebot.providers.registry import PROVIDERS

    return {
        spec.name: (
            spec.display_name or spec.name,
            spec.is_gateway,
            spec.is_local,
            spec.default_api_base,
        )
        for spec in PROVIDERS
        if not spec.is_oauth
    }


def _get_provider_names() -> dict[str, str]:
    """Get provider display names."""
    info = _get_provider_info()
    return {name: data[0] for name, data in info.items() if name}


def _configure_provider(config: Config, provider_name: str) -> None:
    """Configure a single LLM provider."""
    provider_config = getattr(config.providers, provider_name, None)
    if provider_config is None:
        console.print(f"[red]Unknown provider: {provider_name}[/red]")
        return

    display_name = _get_provider_names().get(provider_name, provider_name)
    info = _get_provider_info()
    default_api_base = info.get(provider_name, (None, None, None, None))[3]

    if default_api_base and not provider_config.api_base:
        provider_config.api_base = default_api_base

    updated_provider = _configure_pydantic_model(
        provider_config,
        display_name,
    )
    if updated_provider is not None:
        setattr(config.providers, provider_name, updated_provider)


def _configure_providers(config: Config) -> None:
    """Configure LLM providers."""

    def get_provider_choices() -> list[str]:
        """Build provider choices with config status indicators."""
        choices = []
        for name, display in _get_provider_names().items():
            provider = getattr(config.providers, name, None)
            if provider and provider.api_key:
                choices.append(f"{display} *")
            else:
                choices.append(display)
        return choices + ["<- Back"]

    while True:
        try:
            console.clear()
            _show_section_header("LLM Providers", "Select a provider to configure API key and endpoint")
            choices = get_provider_choices()
            answer = _select_with_back("Select provider:", choices)

            if answer is _BACK_PRESSED or answer is None or answer == "<- Back":
                break

            # Type guard: answer is now guaranteed to be a string
            assert isinstance(answer, str)
            # Extract provider name from choice (remove " *" suffix if present)
            provider_name = answer.replace(" *", "")
            # Find the actual provider key from display names
            for name, display in _get_provider_names().items():
                if display == provider_name:
                    _configure_provider(config, name)
                    break

        except KeyboardInterrupt:
            console.print("\n[dim]Returning to main menu...[/dim]")
            break


# --- Channel Configuration ---


@lru_cache(maxsize=1)
def _get_channel_info() -> dict[str, tuple[str, type[BaseModel]]]:
    """Get channel info (display name + config class) from channel modules."""
    import importlib

    from janniebot.channels.registry import discover_all

    result: dict[str, tuple[str, type[BaseModel]]] = {}
    for name, channel_cls in discover_all().items():
        try:
            mod = importlib.import_module(f"janniebot.channels.{name}")
            config_name = channel_cls.__name__.replace("Channel", "Config")
            config_cls = getattr(mod, config_name, None)
            if config_cls and isinstance(config_cls, type) and issubclass(config_cls, BaseModel):
                display_name = getattr(channel_cls, "display_name", name.capitalize())
                result[name] = (display_name, config_cls)
        except Exception:
            logger.warning(f"Failed to load channel module: {name}")
    return result


def _get_channel_names() -> dict[str, str]:
    """Get channel display names."""
    return {name: info[0] for name, info in _get_channel_info().items()}


def _get_channel_config_class(channel: str) -> type[BaseModel] | None:
    """Get channel config class."""
    entry = _get_channel_info().get(channel)
    return entry[1] if entry else None


def _configure_channel(config: Config, channel_name: str) -> None:
    """Configure a single channel."""
    channel_dict = getattr(config.channels, channel_name, None)
    if channel_dict is None:
        channel_dict = {}
        setattr(config.channels, channel_name, channel_dict)

    display_name = _get_channel_names().get(channel_name, channel_name)
    config_cls = _get_channel_config_class(channel_name)

    if config_cls is None:
        console.print(f"[red]No configuration class found for {display_name}[/red]")
        return

    model = config_cls.model_validate(channel_dict) if channel_dict else config_cls()

    updated_channel = _configure_pydantic_model(
        model,
        display_name,
    )
    if updated_channel is not None:
        new_dict = updated_channel.model_dump(by_alias=True, exclude_none=True)
        setattr(config.channels, channel_name, new_dict)


def _configure_channels(config: Config) -> None:
    """Configure chat channels."""
    channel_names = list(_get_channel_names().keys())
    choices = channel_names + ["<- Back"]

    while True:
        try:
            console.clear()
            _show_section_header("Chat Channels", "Select a channel to configure connection settings")
            answer = _select_with_back("Select channel:", choices)

            if answer is _BACK_PRESSED or answer is None or answer == "<- Back":
                break

            # Type guard: answer is now guaranteed to be a string
            assert isinstance(answer, str)
            _configure_channel(config, answer)
        except KeyboardInterrupt:
            console.print("\n[dim]Returning to main menu...[/dim]")
            break


# --- General Settings ---

_SETTINGS_SECTIONS: dict[str, tuple[str, str, set[str] | None]] = {
    "Agent Settings": ("Agent Defaults", "Configure default model, temperature, and behavior", None),
    "Gateway": ("Gateway Settings", "Configure server host, port, and heartbeat", None),
    "Tools": ("Tools Settings", "Configure web search, shell exec, and other tools", {"mcp_servers"}),
}

_SETTINGS_GETTER = {
    "Agent Settings": lambda c: c.agents.defaults,
    "Gateway": lambda c: c.gateway,
    "Tools": lambda c: c.tools,
}

_SETTINGS_SETTER = {
    "Agent Settings": lambda c, v: setattr(c.agents, "defaults", v),
    "Gateway": lambda c, v: setattr(c, "gateway", v),
    "Tools": lambda c, v: setattr(c, "tools", v),
}


def _configure_general_settings(config: Config, section: str) -> None:
    """Configure a general settings section (header + model edit + writeback)."""
    meta = _SETTINGS_SECTIONS.get(section)
    if not meta:
        return
    display_name, subtitle, skip = meta
    model = _SETTINGS_GETTER[section](config)
    updated = _configure_pydantic_model(model, display_name, skip_fields=skip)
    if updated is not None:
        _SETTINGS_SETTER[section](config, updated)


# --- Summary ---


def _summarize_model(obj: BaseModel) -> list[tuple[str, str]]:
    """Recursively summarize a Pydantic model. Returns list of (field, value) tuples."""
    items: list[tuple[str, str]] = []
    for field_name, field_info in type(obj).model_fields.items():
        value = getattr(obj, field_name, None)
        if value is None or value == "" or value == {} or value == []:
            continue
        display = _get_field_display_name(field_name, field_info)
        ftype = _get_field_type_info(field_info)
        if ftype.type_name == "model" and isinstance(value, BaseModel):
            for nested_field, nested_value in _summarize_model(value):
                items.append((f"{display}.{nested_field}", nested_value))
            continue
        formatted = _format_value(value, rich=False, field_name=field_name)
        if formatted != "[not set]":
            items.append((display, formatted))
    return items


def _print_summary_panel(rows: list[tuple[str, str]], title: str) -> None:
    """Build a two-column summary panel and print it."""
    if not rows:
        return
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    for field, value in rows:
        table.add_row(field, value)
    console.print(Panel(table, title=f"[bold]{title}[/bold]", border_style="blue"))


def _show_summary(config: Config) -> None:
    """Display configuration summary using rich."""
    console.print()

    # Providers
    provider_rows = []
    for name, display in _get_provider_names().items():
        provider = getattr(config.providers, name, None)
        status = "[green]configured[/green]" if (provider and provider.api_key) else "[dim]not configured[/dim]"
        provider_rows.append((display, status))
    _print_summary_panel(provider_rows, "LLM Providers")

    # Channels
    channel_rows = []
    for name, display in _get_channel_names().items():
        channel = getattr(config.channels, name, None)
        if channel:
            enabled = (
                channel.get("enabled", False)
                if isinstance(channel, dict)
                else getattr(channel, "enabled", False)
            )
            status = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
        else:
            status = "[dim]not configured[/dim]"
        channel_rows.append((display, status))
    _print_summary_panel(channel_rows, "Chat Channels")

    # Settings sections
    for title, model in [
        ("Agent Settings", config.agents.defaults),
        ("Gateway", config.gateway),
        ("Tools", config.tools),
        ("Channel Common", config.channels),
    ]:
        _print_summary_panel(_summarize_model(model), title)


# --- Main Entry Point ---


def _has_unsaved_changes(original: Config, current: Config) -> bool:
    """Return True when the onboarding session has committed changes."""
    return original.model_dump(by_alias=True) != current.model_dump(by_alias=True)


def _prompt_main_menu_exit(has_unsaved_changes: bool) -> str:
    """Resolve how to leave the main menu."""
    if not has_unsaved_changes:
        return "discard"

    answer = _get_questionary().select(
        "You have unsaved changes. What would you like to do?",
        choices=[
            "[S] Save and Exit",
            "[X] Exit Without Saving",
            "[R] Resume Editing",
        ],
        default="[R] Resume Editing",
        qmark=">",
    ).ask()

    if answer == "[S] Save and Exit":
        return "save"
    if answer == "[X] Exit Without Saving":
        return "discard"
    return "resume"


def run_onboard(initial_config: Config | None = None) -> OnboardResult:
    """Run the interactive onboarding questionnaire.

    Args:
        initial_config: Optional pre-loaded config to use as starting point.
                       If None, loads from config file or creates new default.
    """
    _get_questionary()

    if initial_config is not None:
        base_config = initial_config.model_copy(deep=True)
    else:
        config_path = get_config_path()
        if config_path.exists():
            base_config = load_config()
        else:
            base_config = Config()

    original_config = base_config.model_copy(deep=True)
    config = base_config.model_copy(deep=True)

    while True:
        console.clear()
        _show_main_menu_header()

        try:
            answer = _get_questionary().select(
                "What would you like to configure?",
                choices=[
                    "[P] LLM Provider",
                    "[C] Chat Channel",
                    "[A] Agent Settings",
                    "[G] Gateway",
                    "[T] Tools",
                    "[V] View Configuration Summary",
                    "[S] Save and Exit",
                    "[X] Exit Without Saving",
                ],
                qmark=">",
            ).ask()
        except KeyboardInterrupt:
            answer = None

        if answer is None:
            action = _prompt_main_menu_exit(_has_unsaved_changes(original_config, config))
            if action == "save":
                return OnboardResult(config=config, should_save=True)
            if action == "discard":
                return OnboardResult(config=original_config, should_save=False)
            continue

        _menu_dispatch = {
            "[P] LLM Provider": lambda: _configure_providers(config),
            "[C] Chat Channel": lambda: _configure_channels(config),
            "[A] Agent Settings": lambda: _configure_general_settings(config, "Agent Settings"),
            "[G] Gateway": lambda: _configure_general_settings(config, "Gateway"),
            "[T] Tools": lambda: _configure_general_settings(config, "Tools"),
            "[V] View Configuration Summary": lambda: _show_summary(config),
        }

        if answer == "[S] Save and Exit":
            return OnboardResult(config=config, should_save=True)
        if answer == "[X] Exit Without Saving":
            return OnboardResult(config=original_config, should_save=False)

        action_fn = _menu_dispatch.get(answer)
        if action_fn:
            action_fn()
