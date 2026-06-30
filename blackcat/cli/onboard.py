"""Interactive onboarding questionnaire for nanobot."""

import asyncio
import json
import types
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, NamedTuple, get_args, get_origin

try:
    import questionary
except ModuleNotFoundError:  # pragma: no cover - exercised in environments without wizard deps
    questionary = None
from loguru import logger
from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nanobot.cli.models import (
    format_token_count,
    get_model_context_limit,
    get_model_suggestions,
)
from nanobot.config.loader import get_config_path, load_config
from nanobot.config.schema import Config, ModelPresetConfig

console = Console()


@dataclass
class OnboardResult:
    """Result of an onboarding session."""

    config: Config
    should_save: bool


class _QuickStartProviderInfo(NamedTuple):
    """Provider metadata used by the Quick Start flow."""

    display_name: str
    is_local: bool
    default_api_base: str
    backend: str
    is_direct: bool


class _QuickStartEndpointChoice(NamedTuple):
    """Provider endpoint option used by Quick Start."""

    label: str
    api_base: str


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

# Cache of model-preset names populated at runtime so that field handlers can
# offer existing presets as choices (e.g. AgentDefaults.model_preset).
_MODEL_PRESET_CACHE: set[str] = set()

_QUICK_START_CUSTOM_PROVIDER_CHOICE = "Other OpenAI-compatible"

_CLEAR_CHOICE = "Clear value"
_QUICK_START_MENU_CHOICE = "[Q] Quick Start"
_QUICK_START_STEPS = ("Provider setup", "WebSocket channel", "Review")
_QUICK_START_ENDPOINT_CHOICES: dict[str, tuple[_QuickStartEndpointChoice, ...]] = {
    "zhipu": (
        _QuickStartEndpointChoice("Standard API", "https://open.bigmodel.cn/api/paas/v4"),
        _QuickStartEndpointChoice("Coding Plan", "https://open.bigmodel.cn/api/coding/paas/v4"),
    ),
    "minimax": (
        _QuickStartEndpointChoice("Global API", "https://api.minimax.io/v1"),
        _QuickStartEndpointChoice("Mainland China Token Plan", "https://api.minimaxi.com/v1"),
    ),
    "minimax_anthropic": (
        _QuickStartEndpointChoice("Global Anthropic API", "https://api.minimax.io/anthropic"),
        _QuickStartEndpointChoice(
            "Mainland China Anthropic Token Plan",
            "https://api.minimaxi.com/anthropic",
        ),
    ),
    "stepfun": (
        _QuickStartEndpointChoice("Standard API", "https://api.stepfun.com/v1"),
        _QuickStartEndpointChoice("Step Plan", "https://api.stepfun.ai/step_plan/v1"),
    ),
    "xiaomi_mimo": (
        _QuickStartEndpointChoice("Standard API", "https://api.xiaomimimo.com/v1"),
        _QuickStartEndpointChoice("Token Plan", "https://token-plan-sgp.xiaomimimo.com/v1"),
    ),
}

# Low-contrast terminal palette inspired by JetBrains Darcula/Islands.
_UI_ACCENT = "#6B9BFA"
_UI_BORDER = "#4E5254"
_UI_TEXT = "#A9B7C6"
_UI_MUTED = "#80868B"
_UI_SUCCESS = "#6AAB73"
_PROMPT_ESCAPE_TIMEOUT_SECONDS = 0.05
_CHANNEL_LOGIN_CHOICE = "Login with QR/link"
_CHANNEL_ADVANCED_CHOICE = "Edit advanced settings"


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
    import shutil

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
    terminal_lines = shutil.get_terminal_size((80, 24)).lines
    visible_count = min(len(choices), max(1, terminal_lines - 3))

    # Build menu items (uses closure over selected_index)
    def get_menu_text():
        items = []
        start, end = _choice_viewport(selected_index, len(choices), visible_count)
        for i in range(start, end):
            choice = choices[i]
            if i == selected_index:
                items.append(("class:selected", f"> {choice}\n"))
            else:
                items.append(("", f"  {choice}\n"))
        return items

    # Create layout
    menu_control = FormattedTextControl(get_menu_text, show_cursor=False)
    menu_window = Window(content=menu_control, height=visible_count, always_hide_cursor=True)

    def get_prompt_text():
        suffix = f" ({selected_index + 1}/{len(choices)})" if len(choices) > visible_count else ""
        return [("class:question", f"{prompt}{suffix}")]

    prompt_control = FormattedTextControl(get_prompt_text, show_cursor=False)
    prompt_window = Window(content=prompt_control, height=1, always_hide_cursor=True)

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
        "selected": f"fg:{_UI_ACCENT} bold",
        "question": f"fg:{_UI_TEXT}",
    })

    app = Application(layout=layout, key_bindings=bindings, style=style)
    app.ttimeoutlen = 0.05
    app.timeoutlen = 0.05
    try:
        app.run()
    except Exception:
        logger.exception("Error in select prompt")
        return None

    return state["result"]


def _choice_viewport(selected_index: int, total: int, visible_count: int) -> tuple[int, int]:
    """Return the visible slice for a long terminal menu."""
    if total <= 0:
        return 0, 0
    visible_count = max(1, min(visible_count, total))
    selected_index = max(0, min(selected_index, total - 1))
    half = visible_count // 2
    start = selected_index - half
    start = max(0, min(start, total - visible_count))
    return start, start + visible_count

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
    if origin is Literal:
        return FieldTypeInfo("literal", list(args))
    return FieldTypeInfo("str", None)


def _get_field_display_name(field_key: str, field_info) -> str:
    """Get display name for a field."""
    if field_info and field_info.description:
        return field_info.description
    name = field_key
    suffix_map = {
        "_s": " seconds",
        "_ms": " ms",
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
        # Handle dicts containing BaseModel instances
        parts = []
        for k, v in value.items():
            formatted = _format_value(v, rich=False, field_name=str(k))
            parts.append(f"{k}: {formatted}")
        return ", ".join(parts) if parts else ("[dim]not set[/dim]" if rich else "[not set]")
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


def _validate_field_constraint(value: Any, field_info) -> str | None:
    """Validate a value against Pydantic Field constraints.

    Returns an error message string if validation fails, None if valid.
    Uses attribute-based detection to handle Pydantic v2 internal types.
    """
    if field_info is None or not hasattr(field_info, "metadata"):
        return None

    for m in field_info.metadata:
        if hasattr(m, "ge") and isinstance(value, (int, float)):
            if value < m.ge:
                return f"Value must be >= {m.ge}"
        if hasattr(m, "gt") and isinstance(value, (int, float)):
            if value <= m.gt:
                return f"Value must be > {m.gt}"
        if hasattr(m, "le") and isinstance(value, (int, float)):
            if value > m.le:
                return f"Value must be <= {m.le}"
        if hasattr(m, "lt") and isinstance(value, (int, float)):
            if value >= m.lt:
                return f"Value must be < {m.lt}"
        if hasattr(m, "min_length") and hasattr(value, "__len__"):
            if len(value) < m.min_length:
                return f"Length must be >= {m.min_length}"
        if hasattr(m, "max_length") and hasattr(value, "__len__"):
            if len(value) > m.max_length:
                return f"Length must be <= {m.max_length}"

    return None


def _get_constraint_hint(field_info) -> str:
    """Derive a human-readable constraint hint from field metadata.

    Returns a string like " - 0-10" or " - >= 0" to append to field display names.
    """
    if field_info is None or not hasattr(field_info, "metadata"):
        return ""

    ge_val = None
    le_val = None
    for m in field_info.metadata:
        if hasattr(m, "ge"):
            ge_val = m.ge
        if hasattr(m, "le"):
            le_val = m.le

    if ge_val is not None and le_val is not None:
        return f" - {ge_val}-{le_val}"
    if ge_val is not None:
        return f" - >= {ge_val}"
    if le_val is not None:
        return f" - <= {le_val}"
    return ""


# --- Rich UI Components ---


def _show_config_panel(display_name: str, model: BaseModel, fields: list) -> None:
    """Display current configuration as a rich table."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style=_UI_ACCENT)
    table.add_column("Value")

    for fname, field_info in fields:
        value = getattr(model, fname, None)
        display = _get_field_display_name(fname, field_info)
        formatted = _format_value(value, rich=True, field_name=fname)
        table.add_row(display, formatted)

    console.print(Panel(table, title=f"[bold {_UI_TEXT}]{display_name}[/]", border_style=_UI_BORDER))


def _show_main_menu_header() -> None:
    """Display the main menu header."""
    from nanobot import __logo__, __version__

    console.print()
    body = Table.grid(expand=True)
    body.add_column(ratio=1)
    body.add_row(f"{__logo__} [bold {_UI_TEXT}]nanobot[/] [{_UI_MUTED}]v{__version__}[/]")
    body.add_row(f"[{_UI_ACCENT}]Quick Start asks for the provider, credentials, and model.[/]")
    body.add_row(
        f"[{_UI_MUTED}]Use Advanced later for chat apps, tools, or provider-specific details.[/]"
    )
    console.print(
        Panel(
            body,
            title=f"[bold {_UI_TEXT}]Setup Wizard[/]",
            border_style=_UI_BORDER,
            padding=(1, 2),
        )
    )
    console.print()


def _show_section_header(title: str, subtitle: str = "") -> None:
    """Display a section header."""
    console.print()
    if subtitle:
        console.print(
            Panel(
                f"[{_UI_MUTED}]{subtitle}[/]",
                title=f"[bold {_UI_TEXT}]{title}[/]",
                border_style=_UI_BORDER,
                padding=(1, 2),
            )
        )
    else:
        console.print(Panel("", title=f"[bold {_UI_TEXT}]{title}[/]", border_style=_UI_BORDER))


# --- Input Handlers ---


def _input_bool(display_name: str, current: bool | None) -> bool | None:
    """Get boolean input via confirm dialog."""
    return _get_questionary().confirm(
        display_name,
        default=bool(current) if current is not None else False,
    ).ask()


def _input_back_key_bindings():
    """Return key bindings that make Escape behave like a local back action."""
    from prompt_toolkit.key_binding import KeyBindings

    bindings = KeyBindings()

    @bindings.add("escape")
    def _escape(event):
        event.app.exit(result=_BACK_PRESSED)

    return bindings


def _ask_prompt(prompt):
    """Ask a questionary prompt with responsive Escape handling."""
    app = getattr(prompt, "application", None)
    if app is not None:
        if hasattr(app, "ttimeoutlen"):
            app.ttimeoutlen = _PROMPT_ESCAPE_TIMEOUT_SECONDS
        if hasattr(app, "timeoutlen"):
            app.timeoutlen = _PROMPT_ESCAPE_TIMEOUT_SECONDS
    return prompt.ask()


def _input_text(display_name: str, current: Any, field_type: str, field_info=None) -> Any:
    """Get text input and parse based on field type."""
    default = _format_value_for_input(current, field_type)

    value = _ask_prompt(
        _get_questionary().text(
            f"{display_name}:",
            default=default,
            key_bindings=_input_back_key_bindings(),
        )
    )

    if value is _BACK_PRESSED or value is None:
        return None if value is None else _BACK_PRESSED

    if field_type == "int":
        try:
            parsed = int(value)
        except ValueError:
            console.print("[yellow]! Invalid number format, value not saved[/yellow]")
            return None
        if field_info:
            error = _validate_field_constraint(parsed, field_info)
            if error:
                console.print(f"[yellow]! {error}, value not saved[/yellow]")
                return None
        return parsed
    elif field_type == "float":
        try:
            parsed = float(value)
        except ValueError:
            console.print("[yellow]! Invalid number format, value not saved[/yellow]")
            return None
        if field_info:
            error = _validate_field_constraint(parsed, field_info)
            if error:
                console.print(f"[yellow]! {error}, value not saved[/yellow]")
                return None
        return parsed
    elif field_type == "list":
        return [v.strip() for v in value.split(",") if v.strip()]
    elif field_type == "dict":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            console.print("[yellow]! Invalid JSON format, value not saved[/yellow]")
            return None

    return value


def _input_secret(display_name: str) -> str | None | object:
    """Get a secret value without echoing it when questionary supports password input."""
    prompt_factory = getattr(_get_questionary(), "password", None)
    if prompt_factory is None:
        prompt_factory = _get_questionary().text
    value = _ask_prompt(prompt_factory(f"{display_name}:", key_bindings=_input_back_key_bindings()))
    if value is _BACK_PRESSED or value is None:
        return None if value is None else _BACK_PRESSED
    return str(value).strip()


def _input_with_existing(
    display_name: str, current: Any, field_type: str, field_info=None
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

    return _input_text(display_name, current, field_type, field_info=field_info)


# --- Pydantic Model Configuration ---


def _get_current_provider(model: BaseModel) -> str:
    """Get the current provider setting from a model (if available)."""
    if hasattr(model, "provider"):
        return getattr(model, "provider", "auto") or "auto"
    return "auto"


def _input_model_with_autocomplete(
    display_name: str, current: Any, provider: str
) -> str | None | object:
    """Get model input with autocomplete suggestions.

    """
    from prompt_toolkit.completion import Completer, Completion

    default = str(current) if current else ""

    class DynamicModelCompleter(Completer):
        """Completer that dynamically fetches model suggestions."""

        def __init__(self, provider_name: str):
            self.provider = provider_name

        def get_completions(self, document, _complete_event):
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

    value = _ask_prompt(
        _get_questionary().autocomplete(
            f"{display_name}:",
            choices=[""],  # Placeholder, actual completions from completer
            completer=DynamicModelCompleter(provider),
            default=default,
            key_bindings=_input_back_key_bindings(),
            qmark=">",
        )
    )

    if value is _BACK_PRESSED or value is None:
        return None if value is None else _BACK_PRESSED
    return value


def _input_context_window_with_recommendation(
    display_name: str, current: Any, model_obj: BaseModel
) -> int | None | object:
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
            console.print(
                f"[{_UI_SUCCESS}]+ Recommended context window: "
                f"{format_token_count(context_limit)} tokens[/]"
            )
            return context_limit
        else:
            console.print("[yellow]! Could not fetch model info, please enter manually[/yellow]")
            # Fall through to manual input

    # Manual input
    value = _get_questionary().text(
        f"{display_name}:",
        default=str(current_val) if current_val else "",
        key_bindings=_input_back_key_bindings(),
    ).ask()

    if value is _BACK_PRESSED:
        return _BACK_PRESSED
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
    if new_value is _BACK_PRESSED:
        return
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
    if new_value is _BACK_PRESSED:
        return
    if new_value is not None:
        setattr(working_model, field_name, new_value)


def _handle_model_preset_field(
    working_model: BaseModel, field_name: str, field_display: str, current_value: Any
) -> None:
    """Handle the 'model_preset' field with a list of existing presets."""
    preset_names = sorted(_MODEL_PRESET_CACHE)
    choices = [_CLEAR_CHOICE] + preset_names
    default_choice = str(current_value) if current_value else _CLEAR_CHOICE
    new_value = _select_with_back(field_display, choices, default=default_choice)
    if new_value is _BACK_PRESSED:
        return
    if new_value == _CLEAR_CHOICE:
        setattr(working_model, field_name, None)
    elif new_value is not None:
        setattr(working_model, field_name, new_value)


def _set_field_from_choices(
    working_model: BaseModel, field_name: str, field_display: str,
    choices: list[str], default_choice: str
) -> None:
    """Prompt to pick one of ``choices`` and set the field (no-op on back/cancel)."""
    new_value = _select_with_back(field_display, choices, default=default_choice)
    if new_value is _BACK_PRESSED:
        return
    if new_value is not None:
        setattr(working_model, field_name, new_value)


def _handle_provider_field(
    working_model: BaseModel, field_name: str, field_display: str, current_value: Any
) -> None:
    """Handle the 'provider' field with a list of registered LLM providers."""
    choices = ["auto"] + sorted(_get_provider_names().keys())
    default_choice = str(current_value) if current_value else "auto"
    _set_field_from_choices(working_model, field_name, field_display, choices, default_choice)


def _handle_fallback_models_field(
    working_model: BaseModel, field_name: str, field_display: str, current_value: Any
) -> None:
    """Handle the 'fallback_models' field with preset-aware list management."""
    from nanobot.config.schema import InlineFallbackConfig

    items: list[Any] = list(current_value) if isinstance(current_value, list) else []
    preset_names = sorted(_MODEL_PRESET_CACHE)

    while True:
        console.clear()
        console.print(f"[bold]{field_display}[/bold]")
        if items:
            for idx, item in enumerate(items, 1):
                if isinstance(item, InlineFallbackConfig):
                    console.print(f"  {idx}. {item.model} - {item.provider} inline")
                else:
                    console.print(f"  {idx}. {item}")
        else:
            console.print("  [dim]empty[/dim]")
        console.print()

        choices = ["[+] Add preset"]
        if items:
            choices.append("[-] Remove last")
            choices.append("[X] Clear all")
        choices.append("[Done]")
        choices.append("<- Back")

        answer = _get_questionary().select(
            "Manage fallback models:",
            choices=choices,
            qmark=">",
        ).ask()

        if answer is None or answer == "<- Back":
            return
        if answer == "[Done]":
            setattr(working_model, field_name, items)
            return
        if answer == "[+] Add preset":
            if not preset_names:
                console.print("[yellow]! No presets defined yet.[/yellow]")
                _get_questionary().press_any_key_to_continue().ask()
                continue
            add_choices = [p for p in preset_names if p not in items]
            if not add_choices:
                console.print("[yellow]! All presets already added.[/yellow]")
                _get_questionary().press_any_key_to_continue().ask()
                continue
            picked = _select_with_back("Select preset:", add_choices)
            if picked is _BACK_PRESSED or picked is None:
                continue
            items.append(picked)
        elif answer == "[-] Remove last" and items:
            items.pop()
        elif answer == "[X] Clear all" and items:
            items.clear()


def _handle_search_provider_field(
    working_model: BaseModel, field_name: str, field_display: str, current_value: Any
) -> None:
    """Handle the web-search 'provider' field with the search-engine list."""
    from nanobot.agent.tools.web import SEARCH_PROVIDER_OPTIONS

    choices = [opt["name"] for opt in SEARCH_PROVIDER_OPTIONS]
    default_choice = current_value if current_value in choices else choices[0]
    _set_field_from_choices(working_model, field_name, field_display, choices, default_choice)


_FIELD_HANDLERS: dict[str, Any] = {
    "model": _handle_model_field,
    "context_window_tokens": _handle_context_window_field,
    "model_preset": _handle_model_preset_field,
    "provider": _handle_provider_field,
    "fallback_models": _handle_fallback_models_field,
}


def _resolve_field_handler(model: BaseModel, field_name: str) -> Any:
    """Resolve the handler for a field. WebSearchConfig shares the bare "provider"
    name with LLM configs but needs the search-engine picker, not the LLM list."""
    if field_name == "provider":
        from nanobot.agent.tools.web import WebSearchConfig
        if isinstance(model, WebSearchConfig):
            return _handle_search_provider_field
    return _FIELD_HANDLERS.get(field_name)


def _is_str_or_none(annotation: Any) -> bool:
    """Check whether a field annotation is ``str | None`` (or ``Optional[str]``)."""
    origin = get_origin(annotation)
    if origin is None:
        return False
    args = get_args(annotation)
    return str in args and type(None) in args


def _configure_pydantic_model(
    model: BaseModel,
    display_name: str,
    *,
    skip_fields: set[str] | None = None,
) -> BaseModel | None:
    """Configure a Pydantic model interactively.

    Returns the updated model when the user selects "Done" or navigates back.
    Cancel actions discard the section draft.
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

    last_field_name: str | None = None
    while True:
        console.clear()
        _show_config_panel(display_name, working_model, fields)
        choices = get_choices()
        default_choice = None
        if last_field_name:
            for idx, (fname, _) in enumerate(fields):
                if fname == last_field_name:
                    default_choice = choices[idx]
                    break
        answer = _select_with_back(
            "Select field to configure:", choices, default=default_choice
        )

        if answer is _BACK_PRESSED:
            return working_model
        if answer is None:
            return None
        if answer == "[Done]":
            return working_model

        field_idx = next((i for i, c in enumerate(choices) if c == answer), -1)
        if field_idx < 0 or field_idx >= len(fields):
            return None

        last_field_name = fields[field_idx][0]

        field_name, field_info = fields[field_idx]
        current_value = getattr(working_model, field_name, None)
        ftype = _get_field_type_info(field_info)
        field_display = _get_field_display_name(field_name, field_info) + _get_constraint_hint(field_info)

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
        handler = _resolve_field_handler(working_model, field_name)
        if handler:
            handler(working_model, field_name, field_display, current_value)
            continue

        # Select fields with hints (e.g. reasoning_effort)
        if field_name in _SELECT_FIELD_HINTS:
            choices_list, hint = _SELECT_FIELD_HINTS[field_name]
            select_choices = choices_list + [_CLEAR_CHOICE]
            console.print(f"[dim]  Hint: {hint}[/dim]")
            new_value = _select_with_back(
                field_display, select_choices, default=current_value or select_choices[0]
            )
            if new_value is _BACK_PRESSED:
                continue
            if new_value == _CLEAR_CHOICE:
                setattr(working_model, field_name, None)
            elif new_value is not None:
                setattr(working_model, field_name, new_value)
            continue

        # Generic field input
        if ftype.type_name == "literal" and ftype.inner_type:
            select_choices = [str(v) for v in ftype.inner_type]
            default_choice = str(current_value) if current_value in ftype.inner_type else select_choices[0]
            new_value = _select_with_back(field_display, select_choices, default=default_choice)
            if new_value is _BACK_PRESSED:
                continue
            if new_value is not None:
                setattr(working_model, field_name, new_value)
            continue
        if ftype.type_name == "bool":
            new_value = _input_bool(field_display, current_value)
        else:
            new_value = _input_with_existing(field_display, current_value, ftype.type_name, field_info=field_info)
        if new_value is _BACK_PRESSED:
            continue
        if new_value is not None:
            # Normalize empty string to None for optional string fields so that
            # clearing an api_key / api_base actually removes the value.
            if new_value == "" and _is_str_or_none(field_info.annotation):
                new_value = None
            setattr(working_model, field_name, new_value)


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

    # Check if current value is the default
    # We only auto-fill if the user hasn't changed it from default
    from nanobot.config.schema import AgentDefaults

    default_context = AgentDefaults.model_fields["context_window_tokens"].default

    if current_context != default_context:
        return  # User has customized it, don't override

    provider = _get_current_provider(model)
    context_limit = get_model_context_limit(new_model_name, provider)

    if context_limit:
        setattr(model, "context_window_tokens", context_limit)
        console.print(
            f"[{_UI_SUCCESS}]+ Auto-filled context window: "
            f"{format_token_count(context_limit)} tokens[/]"
        )
    else:
        console.print("[dim]Could not auto-fill context window - model not in database[/dim]")


# --- Model Preset Configuration ---


def _sync_preset_cache(config: Config) -> None:
    """Synchronise the module-level preset name cache from config."""
    _MODEL_PRESET_CACHE.clear()
    _MODEL_PRESET_CACHE.update(config.model_presets.keys())


def _configure_model_presets(config: Config) -> None:
    """Configure model presets (CRUD)."""
    _sync_preset_cache(config)

    def get_preset_choices() -> tuple[list[str], dict[str, str]]:
        choices: list[str] = []
        choice_to_preset: dict[str, str] = {}
        for name, preset in config.model_presets.items():
            choice = f"{name} - {preset.model}"
            choices.append(choice)
            choice_to_preset[choice] = name
        choices.append("[+] Add new preset")
        choices.append("<- Back")
        return choices, choice_to_preset

    last_preset_name: str | None = None
    while True:
        try:
            console.clear()
            _show_section_header(
                "Model Presets",
                "Create, edit or delete named model presets for quick switching",
            )
            choices, choice_to_preset = get_preset_choices()
            default_choice = None
            if last_preset_name:
                for choice, name in choice_to_preset.items():
                    if name == last_preset_name:
                        default_choice = choice
                        break
            answer = _select_with_back(
                "Select preset:", choices, default=default_choice
            )

            if answer is _BACK_PRESSED or answer is None or answer == "<- Back":
                break

            assert isinstance(answer, str)

            if answer == "[+] Add new preset":
                name_input = _get_questionary().text(
                    "Preset name:",
                    validate=lambda t: True if t and t.strip() else "Name cannot be empty",
                ).ask()
                if not name_input:
                    continue
                name = name_input.strip()
                if name in config.model_presets:
                    console.print(f"[yellow]! Preset '{name}' already exists[/yellow]")
                    _pause()
                    continue
                if name == "default":
                    console.print(
                        "[yellow]! 'default' is reserved; it is generated from Agent Settings[/yellow]"
                    )
                    _pause()
                    continue
                new_preset = ModelPresetConfig(model="")
                updated = _configure_pydantic_model(new_preset, f"New Preset: {name}")
                if updated is not None:
                    config.model_presets[name] = updated
                    _sync_preset_cache(config)
                    last_preset_name = name
                continue

            # Editing / deleting an existing preset
            preset_name = choice_to_preset.get(answer)
            if preset_name is None:
                continue
            preset = config.model_presets.get(preset_name)
            if preset is None:
                continue

            last_preset_name = preset_name

            choices = ["Edit", "Cancel"]
            if preset_name != "default":
                choices.insert(1, "Delete")
            action = _select_with_back(
                f"Preset: {preset_name}",
                choices,
                default="Edit",
            )
            if action is _BACK_PRESSED or action == "Cancel" or action is None:
                continue

            if action == "Delete":
                confirm = _get_questionary().confirm(
                    f"Delete preset '{preset_name}'?",
                    default=False,
                ).ask()
                if confirm:
                    del config.model_presets[preset_name]
                    _sync_preset_cache(config)
                    last_preset_name = None
                continue

            if action == "Edit":
                updated = _configure_pydantic_model(preset, f"Edit Preset: {preset_name}")
                if updated is not None:
                    config.model_presets[preset_name] = updated
                    _sync_preset_cache(config)

        except KeyboardInterrupt:
            console.print("\n[dim]Returning to main menu...[/dim]")
            break


# --- Provider Configuration ---


@lru_cache(maxsize=1)
def _get_provider_info() -> dict[str, tuple[str, bool, bool, str]]:
    """Get provider info from registry (cached)."""
    from nanobot.providers.registry import PROVIDERS

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

    last_provider_key: str | None = None
    while True:
        try:
            console.clear()
            _show_section_header("LLM Providers", "Select a provider to configure API key and endpoint")
            choices = get_provider_choices()
            default_choice = None
            if last_provider_key:
                display = _get_provider_names().get(last_provider_key)
                if display:
                    for c in choices:
                        if c.replace(" *", "") == display:
                            default_choice = c
                            break
            answer = _select_with_back(
                "Select provider:", choices, default=default_choice
            )

            if answer is _BACK_PRESSED or answer is None or answer == "<- Back":
                break

            # Type guard: answer is now guaranteed to be a string
            assert isinstance(answer, str)
            # Extract provider name from choice (remove " *" suffix if present)
            provider_name = answer.replace(" *", "")
            # Find the actual provider key from display names
            for name, display in _get_provider_names().items():
                if display == provider_name:
                    last_provider_key = name
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

    from nanobot.channels.registry import discover_all

    result: dict[str, tuple[str, type[BaseModel]]] = {}
    for name, channel_cls in discover_all().items():
        try:
            mod = importlib.import_module(f"nanobot.channels.{name}")
            config_name = channel_cls.__name__.replace("Channel", "Config")
            config_cls = getattr(mod, config_name, None)
            if config_cls and isinstance(config_cls, type) and issubclass(config_cls, BaseModel):
                display_name = getattr(channel_cls, "display_name", name.capitalize())
                result[name] = (display_name, config_cls)
        except Exception:
            logger.warning("Failed to load channel module: {}", name)
    return result


def _get_channel_names() -> dict[str, str]:
    """Get channel display names."""
    return {name: info[0] for name, info in _get_channel_info().items()}


def _get_channel_config_class(channel: str) -> type[BaseModel] | None:
    """Get channel config class."""
    entry = _get_channel_info().get(channel)
    return entry[1] if entry else None


def _get_channel_class(channel: str) -> type[Any] | None:
    """Get channel implementation class."""
    from nanobot.channels.registry import discover_all

    return discover_all().get(channel)


def _channel_supports_login(channel_cls: type[Any] | None) -> bool:
    """Return True when a channel overrides BaseChannel.login."""
    if channel_cls is None:
        return False
    from nanobot.channels.base import BaseChannel

    return getattr(channel_cls, "login", None) is not BaseChannel.login


def _run_channel_login(
    config: Config,
    channel_name: str,
    model: BaseModel,
    display_name: str,
) -> bool:
    """Run a channel's interactive login and enable it only on success."""
    channel_cls = _get_channel_class(channel_name)
    if channel_cls is None:
        console.print(f"[red]Unknown channel: {channel_name}[/red]")
        return False
    if not _channel_supports_login(channel_cls):
        return False

    if hasattr(model, "enabled"):
        setattr(model, "enabled", True)

    console.print(f"[{_UI_ACCENT}]Starting {display_name} login...[/]")
    try:
        channel = channel_cls(model, bus=None)
        success = asyncio.run(channel.login(force=False))
    except KeyboardInterrupt:
        console.print("\n[dim]Login cancelled.[/dim]")
        return False
    except Exception as exc:
        logger.exception("{} login failed", display_name)
        console.print(f"[red]{display_name} login failed:[/red] {exc}")
        return False

    if not success:
        console.print(f"[yellow]! {display_name} login did not complete; channel was not enabled[/yellow]")
        return False

    setattr(config.channels, channel_name, model.model_dump(by_alias=True, exclude_none=True))
    console.print(f"[{_UI_SUCCESS}]{display_name} enabled[/]")
    return True


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

    channel_cls = _get_channel_class(channel_name)
    if _channel_supports_login(channel_cls):
        action = _select_with_back(
            f"Configure {display_name}:",
            [_CHANNEL_LOGIN_CHOICE, _CHANNEL_ADVANCED_CHOICE, "<- Back"],
            default=_CHANNEL_LOGIN_CHOICE,
        )
        if action is _BACK_PRESSED or action is None or action == "<- Back":
            return
        if action == _CHANNEL_LOGIN_CHOICE:
            _run_channel_login(config, channel_name, model, display_name)
            return

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

    last_choice: str | None = None
    while True:
        try:
            console.clear()
            _show_section_header("Chat Channels", "Select a channel to configure connection settings")
            answer = _select_with_back(
                "Select channel:", choices, default=last_choice
            )

            if answer is _BACK_PRESSED or answer is None or answer == "<- Back":
                break

            # Type guard: answer is now guaranteed to be a string
            assert isinstance(answer, str)
            last_choice = answer
            _configure_channel(config, answer)
        except KeyboardInterrupt:
            console.print("\n[dim]Returning to main menu...[/dim]")
            break


# --- General Settings ---

_SETTINGS_SECTIONS: dict[str, tuple[str, str, set[str] | None]] = {
    "Agent Settings": ("Agent Defaults", "Configure default model, temperature, and behavior", None),
    "Channel Common": ("Channel Common", "Configure cross-channel behavior: progress, tool hints, retries", None),
    "API Server": ("API Server", "Configure OpenAI-compatible API endpoint", None),
    "Gateway": ("Gateway Settings", "Configure server host, port", None),
    "Tools": ("Tools Settings", "Configure web search, shell exec, and other tools", {"mcp_servers"}),
}

_SETTINGS_GETTER = {
    "Agent Settings": lambda c: c.agents.defaults,
    "Channel Common": lambda c: c.channels,
    "API Server": lambda c: c.api,
    "Gateway": lambda c: c.gateway,
    "Tools": lambda c: c.tools,
}

_SETTINGS_SETTER = {
    "Agent Settings": lambda c, v: setattr(c.agents, "defaults", v),
    "Channel Common": lambda c, v: setattr(c, "channels", v),
    "API Server": lambda c, v: setattr(c, "api", v),
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
    table.add_column("Setting", style=_UI_ACCENT)
    table.add_column("Value")
    for field, value in rows:
        table.add_row(field, value)
    console.print(Panel(table, title=f"[bold {_UI_TEXT}]{title}[/]", border_style=_UI_BORDER))


def _show_summary(config: Config) -> None:
    """Display configuration summary using rich."""
    console.print()

    # Providers
    provider_rows = []
    for name, display in _get_provider_names().items():
        provider = getattr(config.providers, name, None)
        status = (
            f"[{_UI_SUCCESS}]configured[/]"
            if (provider and provider.api_key)
            else f"[{_UI_MUTED}]not configured[/]"
        )
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
            status = f"[{_UI_SUCCESS}]enabled[/]" if enabled else f"[{_UI_MUTED}]disabled[/]"
        else:
            status = f"[{_UI_MUTED}]not configured[/]"
        channel_rows.append((display, status))
    _print_summary_panel(channel_rows, "Chat Channels")

    # Model Presets
    preset_rows = []
    for name, preset in config.model_presets.items():
        preset_rows.append((name, f"{preset.model} - ctx {preset.context_window_tokens}"))
    _print_summary_panel(preset_rows, "Model Presets")

    # Settings sections
    for title, model in [
        ("Agent Settings", config.agents.defaults),
        ("Channel Common", config.channels),
        ("API Server", config.api),
        ("Gateway", config.gateway),
        ("Tools", config.tools),
    ]:
        _print_summary_panel(_summarize_model(model), title)

    _pause()


def _pause(message: str = "Press Enter to continue...") -> None:
    """Pause for user acknowledgement before clearing the screen."""
    _get_questionary().text(message, default="").ask()


# --- Quick Start ---


def _set_primary_quick_start_preset(config: Config, provider_name: str, model: str) -> None:
    """Store the primary preset used by Quick Start."""
    config.model_presets["primary"] = ModelPresetConfig(
        label="Primary",
        model=model,
        provider=provider_name,
    )
    config.agents.defaults.model_preset = "primary"
    _sync_preset_cache(config)


def _show_quick_start_progress(active_step: int) -> None:
    """Render a compact step tracker for Quick Start."""
    parts = []
    for idx, label in enumerate(_QUICK_START_STEPS, 1):
        if idx < active_step:
            parts.append(f"[{_UI_SUCCESS}]{idx}. {label}[/]")
        elif idx == active_step:
            parts.append(f"[bold {_UI_ACCENT}]{idx}. {label}[/]")
        else:
            parts.append(f"[{_UI_MUTED}]{idx}. {label}[/]")
    console.print("  " + "  ->  ".join(parts))
    console.print()


@lru_cache(maxsize=1)
def _get_quick_start_provider_info() -> dict[str, _QuickStartProviderInfo]:
    """Return chat-capable providers supported by Quick Start."""
    from nanobot.providers.registry import PROVIDERS

    result: dict[str, _QuickStartProviderInfo] = {}
    for spec in PROVIDERS:
        if spec.name == "custom" or spec.is_oauth or spec.is_transcription_only:
            continue
        result[spec.name] = _QuickStartProviderInfo(
            display_name=spec.display_name or spec.name,
            is_local=spec.is_local,
            default_api_base=spec.default_api_base,
            backend=spec.backend,
            is_direct=spec.is_direct,
        )
    return result


def _get_quick_start_provider_choices() -> dict[str, str]:
    """Return Quick Start provider display choices."""
    choices = {
        info.display_name: provider_name
        for provider_name, info in _get_quick_start_provider_info().items()
    }
    choices[_QUICK_START_CUSTOM_PROVIDER_CHOICE] = "custom"
    return choices


def _quick_start_requires_api_key(provider_name: str, info: _QuickStartProviderInfo | None) -> bool:
    """Return whether Quick Start should ask for an API key."""
    return provider_name == "custom" or not (info and info.is_local)


def _quick_start_requires_base_url(provider_name: str, info: _QuickStartProviderInfo | None) -> bool:
    """Return whether Quick Start must ask for a provider base URL."""
    if provider_name == "custom":
        return True
    if provider_name in _QUICK_START_ENDPOINT_CHOICES:
        return False
    if info is None or info.default_api_base:
        return False
    return info.backend == "azure_openai" or (
        info.backend == "openai_compat" and (info.is_direct or info.is_local)
    )


def _select_quick_start_api_base(
    provider_name: str,
    provider_display: str,
    info: _QuickStartProviderInfo | None,
) -> tuple[str, bool] | None | object:
    """Return the api_base and whether the user explicitly selected or entered it."""
    endpoint_choices = _QUICK_START_ENDPOINT_CHOICES.get(provider_name)
    if endpoint_choices:
        choices = {choice.label: choice.api_base for choice in endpoint_choices}
        answer = _select_with_back(
            f"Which {provider_display} endpoint should Quick Start use?",
            list(choices) + ["<- Back"],
            default=endpoint_choices[0].label,
        )
        if answer is _BACK_PRESSED or answer == "<- Back":
            return _BACK_PRESSED
        if answer is None:
            return None
        assert isinstance(answer, str)
        return choices[answer], True

    api_base = info.default_api_base if info else ""
    if not _quick_start_requires_base_url(provider_name, info):
        return api_base, False

    base_answer = _input_text(
        "Provider base URL",
        api_base,
        "str",
    )
    if base_answer is _BACK_PRESSED:
        return _BACK_PRESSED
    if base_answer is None:
        return None
    api_base = base_answer.strip().rstrip("/")
    if not api_base:
        console.print("[yellow]! Provider base URL is required for this provider[/yellow]")
        return None
    return api_base, True


def _configure_quick_start_provider(config: Config) -> bool | object:
    """Configure the beginner path from provider credentials and model."""
    while True:
        _show_quick_start_progress(1)

        provider_choices = _get_quick_start_provider_choices()
        answer = _select_with_back(
            "Which provider do you want to use?",
            list(provider_choices) + ["<- Back"],
        )
        if answer is _BACK_PRESSED or answer is None or answer == "<- Back":
            return _BACK_PRESSED
        assert isinstance(answer, str)
        provider_name = provider_choices[answer]
        provider_info = _get_quick_start_provider_info().get(provider_name)

        api_base = provider_info.default_api_base if provider_info else ""
        base_was_prompted = False
        if provider_name in _QUICK_START_ENDPOINT_CHOICES:
            api_base_result = _select_quick_start_api_base(provider_name, answer, provider_info)
            if api_base_result is _BACK_PRESSED:
                continue
            if api_base_result is None:
                return False
            api_base, base_was_prompted = api_base_result

        api_key: str | None = None
        if _quick_start_requires_api_key(provider_name, provider_info):
            api_key = _input_text(f"{answer} API key", "", "str")
            if api_key is _BACK_PRESSED:
                continue
            if api_key is None:
                return False
            api_key = api_key.strip()
            if not api_key:
                console.print("[yellow]! API key is required for Quick Start[/yellow]")
                return False

        if (
            provider_name not in _QUICK_START_ENDPOINT_CHOICES
            and _quick_start_requires_base_url(provider_name, provider_info)
        ):
            api_base_result = _select_quick_start_api_base(provider_name, answer, provider_info)
            if api_base_result is _BACK_PRESSED:
                continue
            if api_base_result is None:
                return False
            api_base, base_was_prompted = api_base_result

        provider_config = getattr(config.providers, provider_name, None)
        if provider_config is None:
            console.print(f"[red]Unknown provider: {provider_name}[/red]")
            return False

        model = _input_model_with_autocomplete("Model ID", "", provider_name)
        if model is _BACK_PRESSED:
            continue
        model = (model or "").strip()
        if not model:
            console.print("[yellow]! Model ID is required for Quick Start[/yellow]")
            return False

        if api_key is not None:
            provider_config.api_key = api_key
        if api_base:
            if base_was_prompted:
                provider_config.api_base = api_base
            elif not provider_config.api_base:
                provider_config.api_base = api_base

        _set_primary_quick_start_preset(
            config,
            provider_name,
            model,
        )
        return True


def _enable_quick_start_websocket_defaults(config: Config) -> bool:
    """Enable local WebUI with the default WebSocket settings."""
    _show_quick_start_progress(2)
    console.print(
        f"[{_UI_ACCENT}]Quick Start will enable the WebSocket channel for the local WebUI.[/]"
    )
    console.print(
        f"[{_UI_MUTED}]This lets the browser UI at http://127.0.0.1:8765 connect to nanobot.[/]"
    )
    console.print()
    while True:
        answer = _get_questionary().confirm(
            "Enable WebSocket channel now?",
            default=True,
        ).ask()
        if not answer:
            console.print(
                "[yellow]! Quick Start needs the WebSocket channel for the local WebUI[/yellow]"
            )
            return False
        webui_secret = _input_secret("Set a WebUI password")
        if webui_secret is _BACK_PRESSED:
            continue
        if not webui_secret:
            console.print("[yellow]! WebUI password is required when enabling WebSocket[/yellow]")
            return False
        break

    config_cls = _get_channel_config_class("websocket")
    if config_cls is None:
        console.print("[red]No configuration class found for websocket[/red]")
        return False

    current = getattr(config.channels, "websocket", None) or {}
    model = config_cls.model_validate(current)
    if hasattr(model, "enabled"):
        setattr(model, "enabled", True)
    if hasattr(model, "token_issue_secret"):
        setattr(model, "token_issue_secret", webui_secret)
    if hasattr(model, "websocket_requires_token"):
        setattr(model, "websocket_requires_token", True)
    setattr(config.channels, "websocket", model.model_dump(by_alias=True, exclude_none=True))
    return True


def _show_quick_start_summary(config: Config) -> None:
    """Show the small summary users need before returning to the menu."""
    _show_quick_start_progress(3)
    preset = config.model_presets.get("primary")
    provider_label = "AI provider"
    has_api_key = True
    if preset:
        provider_config = getattr(config.providers, preset.provider, None)
        provider_label, _is_gateway, is_local, _api_base = _get_provider_info().get(
            preset.provider, (preset.provider, False, False, "")
        )
        has_api_key = is_local or bool(provider_config and provider_config.api_key)

    start_command = "`nanobot gateway`"
    next_step = f"Run {start_command}"
    status = "Ready"
    if not has_api_key:
        status = f"{provider_label} API key missing"
        next_step = f"Add your {provider_label} API key, then run {start_command}"

    rows = [
        ("Status", status),
        ("Next", next_step),
        ("WebSocket channel", "enabled"),
        ("Open", "http://127.0.0.1:8765"),
    ]
    _print_summary_panel(rows, "Quick Start")


def _configure_quick_start(config: Config) -> bool:
    """First-run path: provider + API key + local WebUI, with advanced settings hidden."""
    console.clear()
    _show_section_header(
        "Quick Start",
        "Choose provider endpoint, add credentials and model, then enable the local WebUI channel.",
    )
    draft = config.model_copy(deep=True)
    provider_result = _configure_quick_start_provider(draft)
    if provider_result is _BACK_PRESSED:
        return False
    if not provider_result:
        _pause()
        return False
    if not _enable_quick_start_websocket_defaults(draft):
        _pause()
        return False
    _show_quick_start_summary(draft)
    _pause("Press Enter to save and exit...")
    for field_name in type(config).model_fields:
        setattr(config, field_name, getattr(draft, field_name))
    return True


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


def _get_main_menu_choices(has_unsaved_changes: bool) -> list[str]:
    """Return the top-level choices, keeping save actions hidden until needed."""
    choices = [
        _QUICK_START_MENU_CHOICE,
        "[A] Advanced Settings",
    ]
    if has_unsaved_changes:
        choices.extend(["[S] Save and Exit", "[X] Exit Without Saving"])
    else:
        choices.append("[X] Exit")
    return choices


def _configure_advanced_settings(config: Config) -> None:
    """Show lower-frequency setup options behind one advanced menu."""
    last_choice: str | None = None
    choices = [
        "[P] LLM Provider",
        "[M] Model Presets",
        "[C] Chat Channel",
        "[H] Channel Common",
        "[A] Agent Settings",
        "[I] API Server",
        "[G] Gateway",
        "[T] Tools",
        "[V] View Configuration Summary",
        "<- Back",
    ]
    while True:
        try:
            console.clear()
            _show_section_header(
                "Advanced Settings",
                "Use these when the default API-key setup is not enough.",
            )
            answer = _select_with_back(
                "What would you like to configure?",
                choices,
                default=last_choice,
            )
        except KeyboardInterrupt:
            break

        if answer is _BACK_PRESSED or answer is None or answer == "<- Back":
            break

        _advanced_dispatch = {
            "[P] LLM Provider": lambda: _configure_providers(config),
            "[M] Model Presets": lambda: _configure_model_presets(config),
            "[C] Chat Channel": lambda: _configure_channels(config),
            "[H] Channel Common": lambda: _configure_general_settings(config, "Channel Common"),
            "[A] Agent Settings": lambda: _configure_general_settings(config, "Agent Settings"),
            "[I] API Server": lambda: _configure_general_settings(config, "API Server"),
            "[G] Gateway": lambda: _configure_general_settings(config, "Gateway"),
            "[T] Tools": lambda: _configure_general_settings(config, "Tools"),
            "[V] View Configuration Summary": lambda: _show_summary(config),
        }
        action_fn = _advanced_dispatch.get(answer)
        if action_fn:
            last_choice = answer
            action_fn()


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
    _sync_preset_cache(config)

    while True:
        console.clear()
        _show_main_menu_header()

        try:
            answer = _select_with_back(
                "What would you like to do?",
                _get_main_menu_choices(_has_unsaved_changes(original_config, config)),
            )
        except KeyboardInterrupt:
            answer = None

        if answer is _BACK_PRESSED or answer is None:
            action = _prompt_main_menu_exit(_has_unsaved_changes(original_config, config))
            if action == "save":
                return OnboardResult(config=config, should_save=True)
            if action == "discard":
                return OnboardResult(config=original_config, should_save=False)
            continue

        if answer == _QUICK_START_MENU_CHOICE:
            if _configure_quick_start(config):
                return OnboardResult(config=config, should_save=True)
            continue

        if answer == "[S] Save and Exit":
            return OnboardResult(config=config, should_save=True)
        if answer in {"[X] Exit", "[X] Exit Without Saving"}:
            return OnboardResult(config=original_config, should_save=False)
        if answer == "[A] Advanced Settings":
            _configure_advanced_settings(config)
