"""
GUI Input Control Tool for nanobot

将 GUI 控制功能包装为 nanobot 工具系统可调用的工具。
"""

from typing import Any, Optional

from loguru import logger

from nanobot.agent.tools.base import BaseTool


class GUIInputControlTool(BaseTool):
    """图形界面输入控制工具"""
    
    def __init__(self):
        super().__init__()
        self._controller = None
    
    def _get_controller(self):
        """懒加载控制器"""
        if self._controller is None:
            try:
                from nanobot.skills.gui_input_control.gui_control import GUIInputControl
                self._controller = GUIInputControl(pause=0.5, failsafe=True)
            except ImportError as e:
                logger.error(f"Failed to import GUIInputControl: {e}")
                raise
        return self._controller
    
    @property
    def name(self) -> str:
        return "gui_control"
    
    @property
    def description(self) -> str:
        return """Control mouse, keyboard, and screen analysis.
        
Available actions:
- click: Click at coordinates (x, y)
- double_click: Double click at coordinates
- right_click: Right click at coordinates
- move: Move mouse to coordinates
- drag: Drag mouse to coordinates
- type: Type text
- press_key: Press a key (enter, tab, ctrl, etc.)
- hotkey: Press key combination (ctrl+c, ctrl+v, etc.)
- screenshot: Take a screenshot
- ocr: Recognize text on screen
- find_image: Find image on screen
- click_image: Find and click image

Usage examples:
- gui_control(action='click', x=100, y=200)
- gui_control(action='type', text='Hello World')
- gui_control(action='hotkey', keys=['ctrl', 'c'])
- gui_control(action='screenshot', filename='screen.png')
- gui_control(action='ocr', region='100,100,300,200')
- gui_control(action='click_image', image_path='/path/to/button.png')
"""
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform: click, double_click, right_click, move, drag, type, press_key, hotkey, screenshot, ocr, find_image, click_image",
                    "enum": ["click", "double_click", "right_click", "move", "drag", "type", "press_key", "hotkey", "screenshot", "ocr", "find_image", "click_image"]
                },
                "x": {
                    "type": "integer",
                    "description": "X coordinate for mouse actions"
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate for mouse actions"
                },
                "button": {
                    "type": "string",
                    "description": "Mouse button: left, right, middle",
                    "default": "left"
                },
                "text": {
                    "type": "string",
                    "description": "Text to type"
                },
                "key": {
                    "type": "string",
                    "description": "Key to press (for press_key action)"
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keys for hotkey combination (e.g., ['ctrl', 'c'])"
                },
                "filename": {
                    "type": "string",
                    "description": "Filename for screenshot"
                },
                "region": {
                    "type": "string",
                    "description": "Region for screenshot/OCR in format 'left,top,width,height'"
                },
                "lang": {
                    "type": "string",
                    "description": "OCR language code",
                    "default": "chi_sim+eng"
                },
                "image_path": {
                    "type": "string",
                    "description": "Image path for find_image/click_image actions"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence threshold for image matching (0-1)",
                    "default": 0.8
                },
                "duration": {
                    "type": "number",
                    "description": "Duration for mouse movement in seconds",
                    "default": 0.5
                }
            },
            "required": ["action"]
        }
    
    def execute(self, action: str, **kwargs) -> str:
        """Execute GUI control action"""
        try:
            controller = self._get_controller()
            
            if action == "click":
                x = kwargs.get('x')
                y = kwargs.get('y')
                button = kwargs.get('button', 'left')
                controller.click(x, y, button=button)
                return f"Clicked at ({x}, {y}) with {button} button"
            
            elif action == "double_click":
                x = kwargs.get('x')
                y = kwargs.get('y')
                controller.double_click(x, y)
                return f"Double clicked at ({x}, {y})"
            
            elif action == "right_click":
                x = kwargs.get('x')
                y = kwargs.get('y')
                controller.right_click(x, y)
                return f"Right clicked at ({x}, {y})"
            
            elif action == "move":
                x = kwargs.get('x', 0)
                y = kwargs.get('y', 0)
                duration = kwargs.get('duration', 0.5)
                controller.move_mouse(x, y, duration=duration)
                return f"Moved mouse to ({x}, {y})"
            
            elif action == "drag":
                x = kwargs.get('x', 0)
                y = kwargs.get('y', 0)
                duration = kwargs.get('duration', 0.5)
                controller.drag_to(x, y, duration=duration)
                return f"Dragged to ({x}, {y})"
            
            elif action == "type":
                text = kwargs.get('text', '')
                interval = kwargs.get('interval', 0.1)
                controller.type_text(text, interval=interval)
                return f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}"
            
            elif action == "press_key":
                key = kwargs.get('key', '')
                presses = kwargs.get('presses', 1)
                controller.press_key(key, presses=presses)
                return f"Pressed key: {key}"
            
            elif action == "hotkey":
                keys = kwargs.get('keys', [])
                if not keys:
                    return "Error: No keys specified for hotkey"
                controller.hotkey(*keys)
                return f"Pressed hotkey: {'+'.join(keys)}"
            
            elif action == "screenshot":
                filename = kwargs.get('filename', 'screenshot.png')
                region = kwargs.get('region')
                region_tuple = None
                if region:
                    region_tuple = tuple(map(int, region.split(',')))
                controller.screenshot(filename, region=region_tuple)
                return f"Screenshot saved to {filename}"
            
            elif action == "ocr":
                region = kwargs.get('region')
                lang = kwargs.get('lang', 'chi_sim+eng')
                region_tuple = None
                if region:
                    region_tuple = tuple(map(int, region.split(',')))
                text = controller.ocr_text(region=region_tuple, lang=lang)
                return f"OCR Result:\n{text}"
            
            elif action == "find_image":
                image_path = kwargs.get('image_path', '')
                confidence = kwargs.get('confidence', 0.8)
                if not image_path:
                    return "Error: No image_path specified"
                location = controller.locate_image(image_path, confidence)
                if location:
                    center = controller.get_controller().pyautogui.center(location)
                    return f"Found image at: {location}, center: {center}"
                return "Image not found on screen"
            
            elif action == "click_image":
                image_path = kwargs.get('image_path', '')
                confidence = kwargs.get('confidence', 0.8)
                button = kwargs.get('button', 'left')
                if not image_path:
                    return "Error: No image_path specified"
                if controller.click_image(image_path, confidence, button=button):
                    return f"Clicked image: {image_path}"
                return "Image not found, click failed"
            
            else:
                return f"Error: Unknown action '{action}'"
        
        except Exception as e:
            logger.error(f"GUI control error: {e}")
            return f"Error: {e}"
    
    def get_controller(self):
        """Get the underlying controller for advanced usage"""
        return self._get_controller()
