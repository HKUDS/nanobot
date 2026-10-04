"""Dispatch extension API requests to per-extension Python handlers.

An extension may declare an ``api.script`` in its manifest. The referenced
module is loaded from the extension root and must expose::

    def handle(request_path: str, query: dict[str, list[str]], body: bytes) -> tuple[int, dict[str, str], bytes]:
        ...

Handlers run in the gateway process and are trusted the same way config or
installed channel plugins are trusted (the admin installed them). They are
re-imported on each request so a restart is not needed after editing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from nanobot.webui.extensions_api import WebUIExtension

_API_SCRIPT_RELOAD = True


def _load_handler(extension: WebUIExtension) -> Any:
    script = extension.root / extension.api_script
    module_name = f"_nanobot_webui_extension_{extension.id}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load extension api script {extension.api_script}")
    if _API_SCRIPT_RELOAD and module_name in sys.modules:
        del sys.modules[module_name]
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    handler = getattr(module, "handle", None)
    if not callable(handler):
        raise RuntimeError(
            f"extension api script {extension.api_script} must define handle()"
        )
    return handler


def _json_response(payload: Any, status: int = 200) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return (
        status,
        {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-cache"},
        body,
    )


def dispatch_extension_api(
    extension: WebUIExtension,
    request_path: str,
    query: dict[str, list[str]],
    body: bytes,
) -> tuple[int, dict[str, str], bytes]:
    """Call an extension's API handler, returning an HTTP response triple."""
    if not extension.api_script:
        return _json_response({"error": "extension has no api.script"}, status=404)
    try:
        handler = _load_handler(extension)
        result = handler(request_path, query, body)
    except Exception as exc:  # noqa: BLE001 - handler errors are user-facing
        return _json_response({"error": f"extension api error: {exc}"}, status=500)
    if isinstance(result, tuple) and len(result) == 3:
        status, headers, payload = result
        if isinstance(payload, (dict, list)):
            return _json_response(payload, status=status)
        return (status, headers, payload if isinstance(payload, bytes) else str(payload).encode("utf-8"))
    if isinstance(result, (dict, list)):
        return _json_response(result)
    return _json_response({"error": "invalid extension api response"}, status=500)


def extension_script_path(extension: WebUIExtension) -> Path | None:
    """Return the extension's API script path, if declared."""
    return (extension.root / extension.api_script) if extension.api_script else None
