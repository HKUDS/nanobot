"""Persisted WebUI sidebar workspace state.

This state is UI-only metadata, scoped to the active nanobot instance data
directory (the directory containing the current config.json). It deliberately
does not modify agent sessions.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.config.paths import get_webui_dir

WEBUI_SIDEBAR_STATE_SCHEMA_VERSION = 1
_MAX_STATE_FILE_BYTES = 256 * 1024
_MAX_LIST_ITEMS = 2_000
_MAX_MAP_ITEMS = 2_000
_MAX_KEY_LEN = 512
_MAX_TITLE_LEN = 160
_MAX_TAG_LEN = 40
_MAX_WORKBENCH_PANES = 4
_ALLOWED_DENSITIES = {"comfortable", "compact"}
_ALLOWED_SORTS = {"updated_desc", "created_desc", "title_asc", "manual"}
_ALLOWED_WORKBENCH_LAYOUTS = {"columns", "rows", "grid", "bsp", "main-stack"}
_SIDEBAR_STATE_WRITE_LOCK = threading.Lock()


def webui_sidebar_state_path() -> Path:
    return get_webui_dir() / "sidebar-state.json"


def default_webui_sidebar_state() -> dict[str, Any]:
    return {
        "schema_version": WEBUI_SIDEBAR_STATE_SCHEMA_VERSION,
        "pinned_keys": [],
        "archived_keys": [],
        "session_order": [],
        "title_overrides": {},
        "project_name_overrides": {},
        "tags_by_key": {},
        "collapsed_groups": {},
        "workbench": {"version": 1, "tabs": {}},
        "view": {
            "density": "comfortable",
            "show_previews": False,
            "show_timestamps": False,
            "show_archived": False,
            "sort": "updated_desc",
        },
        "updated_at": None,
    }


def _clean_string(value: Any, *, max_len: int = _MAX_KEY_LEN) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def _clean_string_list(value: Any, *, max_len: int = _MAX_KEY_LEN) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in cast(list[Any], value)[:_MAX_LIST_ITEMS]:
        cleaned = _clean_string(item, max_len=max_len)
        if cleaned is None or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _clean_split_ratios(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    ratios: list[float] = []
    for raw_ratio in cast(list[Any], value)[: _MAX_WORKBENCH_PANES - 1]:
        if isinstance(raw_ratio, bool) or not isinstance(raw_ratio, (int, float)):
            continue
        ratio = float(raw_ratio)
        if not math.isfinite(ratio):
            continue
        ratios.append(round(min(0.95, max(0.05, ratio)), 4))
    return ratios


def _clean_bool_map(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, bool] = {}
    for key, raw in list(cast(dict[Any, Any], value).items())[:_MAX_MAP_ITEMS]:
        cleaned_key = _clean_string(key)
        if cleaned_key is None:
            continue
        out[cleaned_key] = bool(raw)
    return out


def _clean_title_overrides(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, raw_title in list(cast(dict[Any, Any], value).items())[:_MAX_MAP_ITEMS]:
        cleaned_key = _clean_string(key)
        cleaned_title = _clean_string(raw_title, max_len=_MAX_TITLE_LEN)
        if cleaned_key is None or cleaned_title is None:
            continue
        out[cleaned_key] = cleaned_title
    return out


def _clean_tags_by_key(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, raw_tags in list(cast(dict[Any, Any], value).items())[:_MAX_MAP_ITEMS]:
        cleaned_key = _clean_string(key)
        if cleaned_key is None:
            continue
        tags = _clean_string_list(raw_tags, max_len=_MAX_TAG_LEN)[:12]
        if tags:
            out[cleaned_key] = tags
    return out


def _clean_view(value: Any) -> dict[str, Any]:
    default: dict[str, Any] = default_webui_sidebar_state()["view"]
    if not isinstance(value, dict):
        return dict(default)
    view = cast(dict[str, Any], value)
    density = view.get("density")
    sort = view.get("sort")
    return {
        "density": density if density in _ALLOWED_DENSITIES else default["density"],
        "show_previews": bool(view.get("show_previews", default["show_previews"])),
        "show_timestamps": bool(view.get("show_timestamps", default["show_timestamps"])),
        "show_archived": bool(view.get("show_archived", default["show_archived"])),
        "sort": sort if sort in _ALLOWED_SORTS else default["sort"],
    }


def _clean_workbench(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"version": 1, "tabs": {}}
    workbench = cast(dict[str, Any], value)
    if workbench.get("version") != 1:
        return {"version": 1, "tabs": {}}
    raw_tabs = workbench.get("tabs")
    if not isinstance(raw_tabs, dict):
        return {"version": 1, "tabs": {}}

    tabs: dict[str, dict[str, Any]] = {}
    claimed_panes: set[str] = set()
    for raw_tab_key, raw_tab in list(cast(dict[Any, Any], raw_tabs).items())[:_MAX_MAP_ITEMS]:
        tab_key = _clean_string(raw_tab_key)
        if tab_key is None or not isinstance(raw_tab, dict):
            continue
        tab = cast(dict[str, Any], raw_tab)
        pane_keys = [
            key
            for key in _clean_string_list(tab.get("paneKeys"))
            if key not in claimed_panes
        ][:_MAX_WORKBENCH_PANES]
        if not pane_keys:
            continue
        explicit = tab.get("explicit") is True
        if not explicit and len(pane_keys) == 1:
            continue
        requested_layout_pane_keys = [
            key for key in _clean_string_list(tab.get("layoutPaneKeys")) if key in pane_keys
        ]
        layout_pane_keys = requested_layout_pane_keys + [
            key for key in pane_keys if key not in requested_layout_pane_keys
        ]
        claimed_panes.update(pane_keys)
        raw_layout = tab.get("layout")
        layout = raw_layout if raw_layout in _ALLOWED_WORKBENCH_LAYOUTS else "columns"
        title = _clean_string(tab.get("title"), max_len=_MAX_TITLE_LEN)
        tabs[tab_key] = {
            "explicit": explicit,
            "title": title,
            "paneKeys": pane_keys,
            "layoutPaneKeys": layout_pane_keys,
            "layout": layout,
            "splitRatios": _clean_split_ratios(tab.get("splitRatios")),
        }
    return {"version": 1, "tabs": tabs}


def normalize_webui_sidebar_state(raw: Any) -> dict[str, Any]:
    """Return a validated canonical sidebar state."""
    if not isinstance(raw, dict):
        raw = {}
    raw = cast(dict[str, Any], raw)
    state = default_webui_sidebar_state()
    state["pinned_keys"] = _clean_string_list(raw.get("pinned_keys"))
    state["archived_keys"] = _clean_string_list(raw.get("archived_keys"))
    state["session_order"] = _clean_string_list(raw.get("session_order"))
    state["title_overrides"] = _clean_title_overrides(raw.get("title_overrides"))
    state["project_name_overrides"] = _clean_title_overrides(
        raw.get("project_name_overrides")
    )
    state["tags_by_key"] = _clean_tags_by_key(raw.get("tags_by_key"))
    state["collapsed_groups"] = _clean_bool_map(raw.get("collapsed_groups"))
    state["workbench"] = _clean_workbench(raw.get("workbench"))
    state["view"] = _clean_view(raw.get("view"))
    updated_at = raw.get("updated_at")
    state["updated_at"] = updated_at if isinstance(updated_at, str) else None
    return state


def read_webui_sidebar_state() -> dict[str, Any]:
    path = webui_sidebar_state_path()
    if not path.is_file():
        return default_webui_sidebar_state()
    try:
        if path.stat().st_size > _MAX_STATE_FILE_BYTES:
            logger.warning("webui sidebar state too large, ignoring: {}", path)
            return default_webui_sidebar_state()
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("read webui sidebar state failed {}: {}", path, e)
        return default_webui_sidebar_state()
    return normalize_webui_sidebar_state(raw)


def write_webui_sidebar_state(raw: dict[str, Any]) -> dict[str, Any]:
    with _SIDEBAR_STATE_WRITE_LOCK:
        return _write_webui_sidebar_state(raw)


def _write_webui_sidebar_state(raw: dict[str, Any]) -> dict[str, Any]:
    state = normalize_webui_sidebar_state(raw)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    encoded = json.dumps(
        state,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _MAX_STATE_FILE_BYTES:
        raise ValueError("sidebar state is too large")

    path = webui_sidebar_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "wb") as f:
        f.write(encoded)
        f.write(b"\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return state
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return state
