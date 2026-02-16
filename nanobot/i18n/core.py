"""Core i18n functionality for nanobot."""

import json
from pathlib import Path
from typing import Any

_locales_dir = Path(__file__).parent / "locales"
_current_locale: str = "en_US"
_translations: dict[str, dict[str, str]] = {}


def _load_translations(locale: str) -> dict[str, str]:
    """Load translations for a specific locale."""
    locale_file = _locales_dir / f"{locale}.json"
    if locale_file.exists():
        with open(locale_file, encoding="utf-8") as f:
            return json.load(f)
    return {}


def set_language(locale: str) -> None:
    """Set the current language/locale."""
    global _current_locale, _translations
    _current_locale = locale
    if locale not in _translations:
        _translations[locale] = _load_translations(locale)


def get_language() -> str:
    """Get the current language/locale."""
    return _current_locale


def t(key: str, **kwargs: Any) -> str:
    """Translate a key to the current locale.

    Args:
        key: Translation key (dot-separated, e.g., "cli.onboard.config_created")
        **kwargs: Variables to format into the translation string

    Returns:
        Translated string, or the key itself if no translation found
    """
    translations = _translations.get(_current_locale, {})
    if _current_locale not in _translations:
        translations = _load_translations(_current_locale)
        _translations[_current_locale] = translations

    parts = key.split(".")
    value: Any = translations
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return key

    if not isinstance(value, str):
        return key

    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, ValueError):
            return value

    return value


def _(key: str, **kwargs: Any) -> str:
    """Shorthand for t() function."""
    return t(key, **kwargs)


def init_from_config() -> None:
    """Initialize language from config file."""
    try:
        from nanobot.config.loader import load_config
        config = load_config()
        locale = getattr(config, "locale", "en_US")
        if locale:
            set_language(locale)
    except Exception:
        set_language("en_US")
