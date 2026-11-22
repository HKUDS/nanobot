"""Localized plain text shared by command receipts and native channel surfaces."""

import json
import os
import re
from functools import cache
from pathlib import Path


@cache
def catalog() -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    for path in sorted((Path(__file__).with_name("command") / "locales").glob("*.json")):
        entries.update(json.loads(path.read_text(encoding="utf-8")))
    return entries


def locale_code(locale: str) -> str:
    tag = locale.split(".")[0].split("@")[0].lower().replace("_", "-")
    base = tag.split("-")[0]
    if base == "zh":
        return "zh-TW" if any(p in {"tw", "hk", "mo", "hant"} for p in tag.split("-")) else "zh-CN"
    return "pt-BR" if base == "pt" else base


def command_text(key: str, locale: object = None, **values: str | int | float) -> str:
    if not isinstance(locale, str) or not locale:
        locale = os.getenv("LC_ALL") or os.getenv("LC_MESSAGES") or os.getenv("LANG") or "en"
    translations = catalog()[key]
    template = translations.get(locale_code(locale), translations["en"])
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m[1]]), template)
