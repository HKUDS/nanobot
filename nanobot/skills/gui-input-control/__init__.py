"""
GUI Input Control Skill

提供系统级鼠标、键盘控制和屏幕内容分析能力。
"""

from nanobot.skills.gui_input_control.gui_control import (
    GUIInputControl,
    gui_click,
    gui_type,
    gui_hotkey,
    gui_screenshot,
    gui_ocr,
    gui_find_image,
    gui_click_image,
)

from nanobot.skills.gui_input_control.tool import GUIInputControlTool

__all__ = [
    'GUIInputControl',
    'GUIInputControlTool',
    'gui_click',
    'gui_type',
    'gui_hotkey',
    'gui_screenshot',
    'gui_ocr',
    'gui_find_image',
    'gui_click_image',
]
