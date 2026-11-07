"""Zalo channel package."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime import MAX_TEXT_LEN, ZaloChannel, ZaloConfig
__all__ = ["MAX_TEXT_LEN", "ZaloChannel", "ZaloConfig"]

def __getattr__(name: str):
    if name in __all__:
        from .runtime import MAX_TEXT_LEN, ZaloChannel, ZaloConfig
        return {"MAX_TEXT_LEN": MAX_TEXT_LEN, "ZaloChannel": ZaloChannel, "ZaloConfig": ZaloConfig}[name]
    raise AttributeError(name)
