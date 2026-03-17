"""Interactive onboarding questionnaire for nanobot."""

import json
import types
from typing import Any, Callable, get_args, get_origin

import questionary
from loguru import logger
from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nanobot.cli.model_info import (
    format_token_count,
    get_model_context_limit,
    get_model_suggestions,
)
from nanobot.config.loader import get_config_path, load_config
from nanobot.config.schema import Config

console = Console()

# --- Field Hints for Select Fields ---
# Maps field names to (choices, hint_text)
# To add a new select field with hints, add an entry:
#   "field_name": (["choice1", "choice2", ...], "hint text for the field")
_SELECT_FIELD_HINTS: dict[str, tuple[list[str], str]] = {
    "reasoning_effort": (
        ["low", "medium", "high"],
        "low / medium / high — enables LLM thinking mode",
    ),
}

# --- Key Bindings for Navigation ---

_BACK_PRESSED = object()  # Sentinel value for back navigation


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
    from prompt_toolkit.application import Application
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
                items.append(("class:selected", f"→ {choice}\n"))
            else:
                items.append(("", f"  {choice}\n"))
        return items

    # Create layout
    menu_control = FormattedTextControl(get_menu_text)
    menu_window = Window(content=menu_control, height=len(choices))

    prompt_control = FormattedTextControl(lambda: [("class:question", f"→ {prompt}")])
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

    app = Application(layout=layout, key_bindings=bindings, style=style)
    try:
        app.run()
    except Exception:
        logger.exception("Error in select prompt")
        return None

    return state["result"]

# --- Type Introspection ---


def _get_field_type_info(field_info) -> tuple[str, Any]:
    """Extract field type info from Pydantic field.

    Returns: (type_name, inner_type)
    - type_name: "str", "int", "float", "bool", "list", "dict", "model"
    - inner_type: for list, the item type; for model, the model class
    """
    annotation = field_info.annotation
    if annotation is None:
        return "str", None

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Handle Optional[T] / T | None
    if origin is types.UnionType:
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            annotation = non_none_args[0]
            origin = get_origin(annotation)
            args = get_args(annotation)

    # Check for list
    if origin is list or (hasattr(origin, "__name__") and origin.__name__ == "List"):
        if args:
            return "list", args[0]
        return "list", str

    # Check for dict
    if origin is dict or (hasattr(origin, "__name__") and origin.__name__ == "Dict"):
        return "dict", None

    # Check for bool
    if annotation is bool or (hasattr(annotation, "__name__") and annotation.__name__ == "bool"):
        return "bool", None

    # Check for int
    if annotation is int or (hasattr(annotation, "__name__") and annotation.__name__ == "int"):
        return "int", None

    # Check for float
    if annotation is float or (hasattr(annotation, "__name__") and annotation.__name__ == "float"):
        return "float", None

    # Check if it's a nested BaseModel
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "model", annotation

    return "str", None


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


# --- Value Formatting ---


def _format_value(value: Any, rich: bool = True) -> str:
    """Format a value for display."""
    if value is None or value == "" or value == {} or value == []:
        return "[dim]not set[/dim]" if rich else "[not set]"
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

    for field_name, field_info in fields:
        value = getattr(model, field_name, None)
        display = _get_field_display_name(field_name, field_info)
        formatted = _format_value(value, rich=True)
        table.add_row(display, formatted)

    console.print(Panel(table, title=f"[bold]{display_name}[/bold]", border_style="blue"))


def _show_main_menu_header() -> None:
    """Display the main menu header."""
    from nanobot import __logo__, __version__

    console.print()
    # Use Align.CENTER for the single line of text
    from rich.align import Align

    console.print(
        Align.center(f"{__logo__} [bold cyan]nanobot[{__version__}][/bold cyan]")
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
    return questionary.confirm(
        display_name,
        default=bool(current) if current is not None else False,
    ).ask()


def _input_text(display_name: str, current: Any, field_type: str) -> Any:
    """Get text input and parse based on field type."""
    default = _format_value_for_input(current, field_type)

    value = questionary.text(f"{display_name}:", default=default).ask()

    if value is None or value == "":
        return None

    if field_type == "int":
        try:
            return int(value)
        except ValueError:
            console.print("[yellow]⚠ Invalid number format, value not saved[/yellow]")
            return None
    elif field_type == "float":
        try:
            return float(value)
        except ValueError:
            console.print("[yellow]⚠ Invalid number format, value not saved[/yellow]")
            return None
    elif field_type == "list":
        return [v.strip() for v in value.split(",") if v.strip()]
    elif field_type == "dict":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            console.print("[yellow]⚠ Invalid JSON format, value not saved[/yellow]")
            return None

    return value


def _input_with_existing(
    display_name: str, current: Any, field_type: str
) -> Any:
    """Handle input with 'keep existing' option for non-empty values."""
    has_existing = current is not None and current != "" and current != {} and current != []

    if has_existing and not isinstance(current, list):
        choice = questionary.select(
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

    value = questionary.autocomplete(
        f"{display_name}:",
        choices=[""],  # Placeholder, actual completions from completer
        completer=DynamicModelCompleter(provider),
        default=default,
        qmark="→",
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
    choices.append("🔍 Get recommended value")

    choice = questionary.select(
        display_name,
        choices=choices,
        default="Enter new value",
    ).ask()

    if choice is None:
        return None

    if choice == "Keep existing value":
        return None

    if choice == "🔍 Get recommended value":
        # Get the model name from the model object
        model_name = getattr(model_obj, "model", None)
        if not model_name:
            console.print("[yellow]⚠ Please configure the model field first[/yellow]")
            return None

        provider = _get_current_provider(model_obj)
        context_limit = get_model_context_limit(model_name, provider)

        if context_limit:
            console.print(f"[green]✓ Recommended context window: {format_token_count(context_limit)} tokens[/green]")
            return context_limit
        else:
            console.print("[yellow]⚠ Could not fetch model info, please enter manually[/yellow]")
            # Fall through to manual input

    # Manual input
    value = questionary.text(
        f"{display_name}:",
        default=str(current_val) if current_val else "",
    ).ask()

    if value is None or value == "":
        return None

    try:
        return int(value)
    except ValueError:
        console.print("[yellow]⚠ Invalid number format, value not saved[/yellow]")
        return None


def _configure_pydantic_model(
    model: BaseModel,
    display_name: str,
    *,
    skip_fields: set[str] | None = None,
    finalize_hook: Callable | None = None,
) -> None:
    """Configure a Pydantic model interactively."""
    skip_fields = skip_fields or set()

    fields = []
    for field_name, field_info in type(model).model_fields.items():
        if field_name in skip_fields:
            continue
        fields.append((field_name, field_info))

    if not fields:
        console.print(f"[dim]{display_name}: No configurable fields[/dim]")
        return

    def get_choices() -> list[str]:
        choices = []
        for field_name, field_info in fields:
            value = getattr(model, field_name, None)
            display = _get_field_display_name(field_name, field_info)
            formatted = _format_value(value, rich=False)
            choices.append(f"{display}: {formatted}")
        return choices + ["✓ Done"]

    while True:
        _show_config_panel(display_name, model, fields)
        choices = get_choices()

        answer = _select_with_back("Select field to configure:", choices)

        if answer is _BACK_PRESSED:
            # User pressed Escape or Left arrow - go back
            if finalize_hook:
                finalize_hook(model)
            break

        if answer == "✓ Done" or answer is None:
            if finalize_hook:
                finalize_hook(model)
            break

        field_idx = next((i for i, c in enumerate(choices) if c == answer), -1)
        if field_idx < 0 or field_idx >= len(fields):
            break

        field_name, field_info = fields[field_idx]
        current_value = getattr(model, field_name, None)
        field_type, _ = _get_field_type_info(field_info)
        field_display = _get_field_display_name(field_name, field_info)

        if field_type == "model":
            nested_model = current_value
            if nested_model is None:
                _, nested_cls = _get_field_type_info(field_info)
                if nested_cls:
                    nested_model = nested_cls()
                    setattr(model, field_name, nested_model)

            if nested_model and isinstance(nested_model, BaseModel):
                _configure_pydantic_model(nested_model, field_display)
            continue

        # Special handling for model field (autocomplete)
        if field_name == "model":
            provider = _get_current_provider(model)
            new_value = _input_model_with_autocomplete(field_display, current_value, provider)
            if new_value is not None and new_value != current_value:
                setattr(model, field_name, new_value)
                # Auto-fill context_window_tokens if it's at default value
                _try_auto_fill_context_window(model, new_value)
            continue

        # Special handling for context_window_tokens field
        if field_name == "context_window_tokens":
            new_value = _input_context_window_with_recommendation(field_display, current_value, model)
            if new_value is not None:
                setattr(model, field_name, new_value)
            continue

        # Special handling for select fields with hints (e.g., reasoning_effort)
        if field_name in _SELECT_FIELD_HINTS:
            choices_list, hint = _SELECT_FIELD_HINTS[field_name]
            select_choices = choices_list + ["(clear/unset)"]
            console.print(f"[dim]  Hint: {hint}[/dim]")
            new_value = _select_with_back(field_display, select_choices, default=current_value or select_choices[0])
            if new_value is _BACK_PRESSED:
                continue
            if new_value == "(clear/unset)":
                setattr(model, field_name, None)
            elif new_value is not None:
                setattr(model, field_name, new_value)
            continue

        if field_type == "bool":
            new_value = _input_bool(field_display, current_value)
            if new_value is not None:
                setattr(model, field_name, new_value)
        else:
            new_value = _input_with_existing(field_display, current_value, field_type)
            if new_value is not None:
                setattr(model, field_name, new_value)


def _try_auto_fill_context_window(model: BaseModel, new_model_name: str) -> None:
    """Try to auto-fill context_window_tokens if it's at default value.

    Note:
        This function imports AgentDefaults from nanobot.config.schema to get
        the default context_window_tokens value. If the schema changes, this
        coupling needs to be updated accordingly.
    """
    # Check if context_window_tokens field exists
    if not hasattr(model, "context_window_tokens"):
        return

    current_context = getattr(model, "context_window_tokens", None)

    # Check if current value is the default (65536)
    # We only auto-fill if the user hasn't changed it from default
    from nanobot.config.schema import AgentDefaults

    default_context = AgentDefaults.model_fields["context_window_tokens"].default

    if current_context != default_context:
        return  # User has customized it, don't override

    provider = _get_current_provider(model)
    context_limit = get_model_context_limit(new_model_name, provider)

    if context_limit:
        setattr(model, "context_window_tokens", context_limit)
        console.print(f"[green]✓ Auto-filled context window: {format_token_count(context_limit)} tokens[/green]")
    else:
        console.print("[dim]ℹ Could not auto-fill context window (model not in database)[/dim]")


# --- Provider Configuration ---


_PROVIDER_INFO: dict[str, tuple[str, bool, bool, str]] | None = None


def _get_provider_info() -> dict[str, tuple[str, bool, bool, str]]:
    """Get provider info from registry (cached)."""
    global _PROVIDER_INFO
    if _PROVIDER_INFO is None:
        from nanobot.providers.registry import PROVIDERS

        _PROVIDER_INFO = {}
        for spec in PROVIDERS:
            _PROVIDER_INFO[spec.name] = (
                spec.display_name or spec.name,
                spec.is_gateway,
                spec.is_local,
                spec.default_api_base,
            )
    return _PROVIDER_INFO


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

    _configure_pydantic_model(
        provider_config,
        display_name,
    )


def _configure_providers(config: Config) -> None:
    """Configure LLM providers."""
    _show_section_header("LLM Providers", "Select a provider to configure API key and endpoint")

    def get_provider_choices() -> list[str]:
        """Build provider choices with config status indicators."""
        choices = []
        for name, display in _get_provider_names().items():
            provider = getattr(config.providers, name, None)
            if provider and provider.api_key:
                choices.append(f"{display} ✓")
            else:
                choices.append(display)
        return choices + ["← Back"]

    while True:
        try:
            choices = get_provider_choices()
            answer = _select_with_back("Select provider:", choices)

            if answer is _BACK_PRESSED or answer is None or answer == "← Back":
                break

            # Type guard: answer is now guaranteed to be a string
            assert isinstance(answer, str)
            # Extract provider name from choice (remove " ✓" suffix if present)
            provider_name = answer.replace(" ✓", "")
            # Find the actual provider key from display names
            for name, display in _get_provider_names().items():
                if display == provider_name:
                    _configure_provider(config, name)
                    break

        except KeyboardInterrupt:
            console.print("\n[dim]Returning to main menu...[/dim]")
            break


# --- Channel Configuration ---


def _get_channel_info() -> dict[str, tuple[str, type[BaseModel]]]:
    """Get channel info (display name + config class) from channel modules."""
    import importlib

    from nanobot.channels.registry import discover_all

    result = {}
    for name, channel_cls in discover_all().items():
        try:
            mod = importlib.import_module(f"nanobot.channels.{name}")
            config_cls = None
            display_name = name.capitalize()
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseModel) and attr is not BaseModel:
                    if "Config" in attr_name:
                        config_cls = attr
                        if hasattr(channel_cls, "display_name"):
                            display_name = channel_cls.display_name
                        break

            if config_cls:
                result[name] = (display_name, config_cls)
        except Exception:
            logger.warning(f"Failed to load channel module: {name}")
    return result


_CHANNEL_INFO: dict[str, tuple[str, type[BaseModel]]] | None = None


def _get_channel_names() -> dict[str, str]:
    """Get channel display names."""
    global _CHANNEL_INFO
    if _CHANNEL_INFO is None:
        _CHANNEL_INFO = _get_channel_info()
    return {name: info[0] for name, info in _CHANNEL_INFO.items() if name}


def _get_channel_config_class(channel: str) -> type[BaseModel] | None:
    """Get channel config class."""
    global _CHANNEL_INFO
    if _CHANNEL_INFO is None:
        _CHANNEL_INFO = _get_channel_info()
    return _CHANNEL_INFO.get(channel, (None, None))[1]


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

    def finalize(model: BaseModel):
        new_dict = model.model_dump(by_alias=True, exclude_none=True)
        setattr(config.channels, channel_name, new_dict)

    _configure_pydantic_model(
        model,
        display_name,
        finalize_hook=finalize,
    )


def _configure_channels(config: Config) -> None:
    """Configure chat channels."""
    _show_section_header("Chat Channels", "Select a channel to configure connection settings")

    channel_names = list(_get_channel_names().keys())
    choices = channel_names + ["← Back"]

    while True:
        try:
            answer = _select_with_back("Select channel:", choices)

            if answer is _BACK_PRESSED or answer is None or answer == "← Back":
                break

            # Type guard: answer is now guaranteed to be a string
            assert isinstance(answer, str)
            _configure_channel(config, answer)
        except KeyboardInterrupt:
            console.print("\n[dim]Returning to main menu...[/dim]")
            break


# --- General Settings ---


def _configure_general_settings(config: Config, section: str) -> None:
    """Configure a general settings section."""
    section_map = {
        "Agent Settings": (config.agents.defaults, "Agent Defaults"),
        "Gateway": (config.gateway, "Gateway Settings"),
        "Tools": (config.tools, "Tools Settings"),
        "Channel Common": (config.channels, "Channel Common Settings"),
    }

    if section not in section_map:
        return

    model, display_name = section_map[section]

    if section == "Tools":
        _configure_pydantic_model(
            model,
            display_name,
            skip_fields={"mcp_servers"},
        )
    else:
        _configure_pydantic_model(model, display_name)


def _configure_agents(config: Config) -> None:
    """Configure agent settings."""
    _show_section_header("Agent Settings", "Configure default model, temperature, and behavior")
    _configure_general_settings(config, "Agent Settings")


def _configure_gateway(config: Config) -> None:
    """Configure gateway settings."""
    _show_section_header("Gateway", "Configure server host, port, and heartbeat")
    _configure_general_settings(config, "Gateway")


def _configure_tools(config: Config) -> None:
    """Configure tools settings."""
    _show_section_header("Tools", "Configure web search, shell exec, and other tools")
    _configure_general_settings(config, "Tools")


# --- Summary ---


def _summarize_model(obj: BaseModel, indent: int = 2) -> list[tuple[str, str]]:
    """Recursively summarize a Pydantic model. Returns list of (field, value) tuples."""
    items = []

    for field_name, field_info in type(obj).model_fields.items():
        value = getattr(obj, field_name, None)
        field_type, _ = _get_field_type_info(field_info)

        if value is None or value == "" or value == {} or value == []:
            continue

        display = _get_field_display_name(field_name, field_info)

        if field_type == "model" and isinstance(value, BaseModel):
            nested_items = _summarize_model(value, indent)
            for nested_field, nested_value in nested_items:
                items.append((f"{display}.{nested_field}", nested_value))
            continue

        formatted = _format_value(value, rich=False)
        if formatted != "[not set]":
            items.append((display, formatted))

    return items


def _show_summary(config: Config) -> None:
    """Display configuration summary using rich."""
    console.print()

    # Providers table
    provider_table = Table(show_header=False, box=None, padding=(0, 2))
    provider_table.add_column("Provider", style="cyan")
    provider_table.add_column("Status")

    for name, display in _get_provider_names().items():
        provider = getattr(config.providers, name, None)
        if provider and provider.api_key:
            provider_table.add_row(display, "[green]✓ configured[/green]")
        else:
            provider_table.add_row(display, "[dim]not configured[/dim]")

    console.print(Panel(provider_table, title="[bold]LLM Providers[/bold]", border_style="blue"))

    # Channels table
    channel_table = Table(show_header=False, box=None, padding=(0, 2))
    channel_table.add_column("Channel", style="cyan")
    channel_table.add_column("Status")

    for name, display in _get_channel_names().items():
        channel = getattr(config.channels, name, None)
        if channel:
            enabled = (
                channel.get("enabled", False)
                if isinstance(channel, dict)
                else getattr(channel, "enabled", False)
            )
            if enabled:
                channel_table.add_row(display, "[green]✓ enabled[/green]")
            else:
                channel_table.add_row(display, "[dim]disabled[/dim]")
        else:
            channel_table.add_row(display, "[dim]not configured[/dim]")

    console.print(Panel(channel_table, title="[bold]Chat Channels[/bold]", border_style="blue"))

    # Agent Settings
    agent_items = _summarize_model(config.agents.defaults)
    if agent_items:
        agent_table = Table(show_header=False, box=None, padding=(0, 2))
        agent_table.add_column("Setting", style="cyan")
        agent_table.add_column("Value")
        for field, value in agent_items:
            agent_table.add_row(field, value)
        console.print(Panel(agent_table, title="[bold]Agent Settings[/bold]", border_style="blue"))

    # Gateway
    gateway_items = _summarize_model(config.gateway)
    if gateway_items:
        gw_table = Table(show_header=False, box=None, padding=(0, 2))
        gw_table.add_column("Setting", style="cyan")
        gw_table.add_column("Value")
        for field, value in gateway_items:
            gw_table.add_row(field, value)
        console.print(Panel(gw_table, title="[bold]Gateway[/bold]", border_style="blue"))

    # Tools
    tools_items = _summarize_model(config.tools)
    if tools_items:
        tools_table = Table(show_header=False, box=None, padding=(0, 2))
        tools_table.add_column("Setting", style="cyan")
        tools_table.add_column("Value")
        for field, value in tools_items:
            tools_table.add_row(field, value)
        console.print(Panel(tools_table, title="[bold]Tools[/bold]", border_style="blue"))

    # Channel Common
    channel_common_items = _summarize_model(config.channels)
    if channel_common_items:
        cc_table = Table(show_header=False, box=None, padding=(0, 2))
        cc_table.add_column("Setting", style="cyan")
        cc_table.add_column("Value")
        for field, value in channel_common_items:
            cc_table.add_row(field, value)
        console.print(Panel(cc_table, title="[bold]Channel Common[/bold]", border_style="blue"))


# --- Main Entry Point ---


def run_onboard(initial_config: Config | None = None) -> Config:
    """Run the interactive onboarding questionnaire.

    Args:
        initial_config: Optional pre-loaded config to use as starting point.
                       If None, loads from config file or creates new default.
    """
    if initial_config is not None:
        config = initial_config
    else:
        config_path = get_config_path()
        if config_path.exists():
            config = load_config()
        else:
            config = Config()

    while True:
        try:
            _show_main_menu_header()

            answer = questionary.select(
                "What would you like to configure?",
                choices=[
                    "🔌 Configure LLM Provider",
                    "💬 Configure Chat Channel",
                    "⚙️ Configure Channel Common",
                    "🤖 Configure Agent Settings",
                    "🌐 Configure Gateway",
                    "🔧 Configure Tools",
                    "📋 View Configuration Summary",
                    "💾 Save and Exit",
                ],
                qmark="→",
            ).ask()

            if answer == "🔌 Configure LLM Provider":
                _configure_providers(config)
            elif answer == "💬 Configure Chat Channel":
                _configure_channels(config)
            elif answer == "⚙️ Configure Channel Common":
                _configure_general_settings(config, "Channel Common")
            elif answer == "🤖 Configure Agent Settings":
                _configure_agents(config)
            elif answer == "🌐 Configure Gateway":
                _configure_gateway(config)
            elif answer == "🔧 Configure Tools":
                _configure_tools(config)
            elif answer == "📋 View Configuration Summary":
                _show_summary(config)
            elif answer == "💾 Save and Exit":
                break
        except KeyboardInterrupt:
            console.print(
                "\n\n[yellow]Operation cancelled. Use 'Save and Exit' to save changes.[/yellow]"
            )
            break

    return config
