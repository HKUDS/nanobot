"""Web UI package — FastAPI backend for assistant-ui frontend."""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str) -> object:  # noqa: N807
    if name == "create_app":
        from nanobot.web.app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
