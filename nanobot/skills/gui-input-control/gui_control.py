"""
GUI Input Control Tool - 图形界面输入控制工具

提供系统级鼠标、键盘控制和屏幕内容分析能力。
适用于 WSL + WSLg 环境和 Linux 桌面环境。
"""

import os
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False
    logger.warning("pyautogui not installed. Run: pip install pyautogui pillow")

try:
    import pytesseract
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False
    logger.warning("pytesseract not installed. Run: pip install pytesseract")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("PIL not installed. Run: pip install pillow")


class GUIInputControl:
    """图形界面输入控制类"""
    
    def __init__(self, pause: float = 0.5, failsafe: bool = True):
        """
        初始化 GUI 控制器
        
        Args:
            pause: 每次操作后的等待时间（秒）
            failsafe: 是否启用故障保护（鼠标移到左上角触发异常）
        """
        if not HAS_PYAUTOGUI:
            raise ImportError("pyautogui is required. Install with: pip install pyautogui")
        
        # 安全设置
        pyautogui.PAUSE = pause
        pyautogui.FAILSAFE = failsafe
        
        # 检查 DISPLAY 环境变量（WSL 环境）
        if not os.environ.get('DISPLAY'):
            logger.warning("DISPLAY environment variable not set. Set with: export DISPLAY=:0")
        
        logger.info(f"GUI Input Control initialized (pause={pause}s, failsafe={failsafe})")
    
    def get_screen_size(self) -> tuple[int, int]:
        """获取屏幕分辨率"""
        return pyautogui.size()
    
    def get_mouse_position(self) -> tuple[int, int]:
        """获取当前鼠标位置"""
        return pyautogui.position()
    
    def move_mouse(self, x: int, y: int, duration: float = 0.5):
        """
        移动鼠标到指定坐标
        
        Args:
            x: X 坐标
            y: Y 坐标
            duration: 移动时间（秒），0 表示瞬间移动
        """
        logger.debug(f"Moving mouse to ({x}, {y}) in {duration}s")
        pyautogui.moveTo(x, y, duration=duration)
    
    def move_mouse_relative(self, x_offset: int, y_offset: int, duration: float = 0.3):
        """
        相对移动鼠标
        
        Args:
            x_offset: X 偏移量
            y_offset: Y 偏移量
            duration: 移动时间（秒）
        """
        logger.debug(f"Moving mouse relative ({x_offset}, {y_offset})")
        pyautogui.moveRel(x_offset, y_offset, duration=duration)
    
    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left', clicks: int = 1):
        """
        点击鼠标
        
        Args:
            x: X 坐标（None 表示当前位置）
            y: Y 坐标（None 表示当前位置）
            button: 按钮类型 ('left', 'right', 'middle')
            clicks: 点击次数
        """
        if x is not None and y is not None:
            self.move_mouse(x, y, duration=0.2)
        
        logger.debug(f"Clicking {button} button {clicks} time(s)")
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    
    def double_click(self, x: Optional[int] = None, y: Optional[int] = None):
        """双击"""
        self.click(x, y, button='left', clicks=2)
    
    def right_click(self, x: Optional[int] = None, y: Optional[int] = None):
        """右键点击"""
        self.click(x, y, button='right', clicks=1)
    
    def drag_to(self, x: int, y: int, duration: float = 0.5, button: str = 'left'):
        """
        拖拽到指定位置
        
        Args:
            x: 目标 X 坐标
            y: 目标 Y 坐标
            duration: 拖拽时间（秒）
            button: 鼠标按钮
        """
        logger.debug(f"Dragging to ({x}, {y}) in {duration}s")
        pyautogui.dragTo(x, y, duration=duration, button=button)
    
    def mouse_down(self, button: str = 'left'):
        """按住鼠标按钮"""
        logger.debug(f"Mouse down ({button})")
        pyautogui.mouseDown(button=button)
    
    def mouse_up(self, button: str = 'left'):
        """松开鼠标按钮"""
        logger.debug(f"Mouse up ({button})")
        pyautogui.mouseUp(button=button)
    
    def type_text(self, text: str, interval: float = 0.1):
        """
        输入文字
        
        Args:
            text: 要输入的文字
            interval: 每个字符之间的间隔（秒）
        """
        logger.debug(f"Typing text: {text[:50]}...")
        pyautogui.write(text, interval=interval)
    
    def press_key(self, key: str | list[str], presses: int = 1):
        """
        按键
        
        Args:
            key: 键名（如 'enter', 'tab', 'ctrl'）或键名列表
            presses: 按压次数
        """
        logger.debug(f"Pressing key: {key}")
        pyautogui.press(key, presses=presses)
    
    def hotkey(self, *keys: str):
        """
        快捷键组合
        
        Args:
            keys: 键名列表（如 'ctrl', 'c'）
        """
        logger.debug(f"Pressing hotkey: {'+'.join(keys)}")
        pyautogui.hotkey(*keys)
    
    def key_down(self, key: str):
        """按住键"""
        logger.debug(f"Key down: {key}")
        pyautogui.keyDown(key)
    
    def key_up(self, key: str):
        """松开键"""
        logger.debug(f"Key up: {key}")
        pyautogui.keyUp(key)
    
    def screenshot(self, filename: Optional[str] = None, region: Optional[tuple] = None) -> Image.Image:
        """
        屏幕截图
        
        Args:
            filename: 保存文件名（None 表示不保存）
            region: 截图区域 (left, top, width, height)
        
        Returns:
            PIL Image 对象
        """
        logger.debug(f"Taking screenshot (region={region})")
        screenshot = pyautogui.screenshot(region=region)
        
        if filename:
            screenshot.save(filename)
            logger.info(f"Screenshot saved to {filename}")
        
        return screenshot
    
    def get_pixel_color(self, x: int, y: int) -> tuple[int, int, int]:
        """
        获取指定位置的像素颜色
        
        Args:
            x: X 坐标
            y: Y 坐标
        
        Returns:
            RGB 颜色元组 (R, G, B)
        """
        return pyautogui.pixel(x, y)
    
    def locate_image(self, image_path: str, confidence: float = 0.8, region: Optional[tuple] = None) -> Optional[tuple]:
        """
        在屏幕上查找图片位置
        
        Args:
            image_path: 图片路径
            confidence: 匹配置信度 (0-1)
            region: 搜索区域 (left, top, width, height)
        
        Returns:
            位置元组 (left, top, width, height) 或 None
        """
        if not Path(image_path).exists():
            logger.error(f"Image not found: {image_path}")
            return None
        
        logger.debug(f"Locating image: {image_path} (confidence={confidence})")
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence, region=region)
            if location:
                logger.info(f"Image found at: {location}")
            else:
                logger.warning("Image not found on screen")
            return location
        except Exception as e:
            logger.error(f"Error locating image: {e}")
            return None
    
    def locate_all_images(self, image_path: str, confidence: float = 0.8) -> list[tuple]:
        """
        查找屏幕上所有匹配的图片位置
        
        Args:
            image_path: 图片路径
            confidence: 匹配置信度
        
        Returns:
            位置列表
        """
        if not Path(image_path).exists():
            logger.error(f"Image not found: {image_path}")
            return []
        
        logger.debug(f"Locating all instances of: {image_path}")
        locations = list(pyautogui.locateAllOnScreen(image_path, confidence=confidence))
        logger.info(f"Found {len(locations)} matches")
        return locations
    
    def click_image(self, image_path: str, confidence: float = 0.8, button: str = 'left') -> bool:
        """
        查找并点击图片
        
        Args:
            image_path: 图片路径
            confidence: 匹配置信度
            button: 鼠标按钮
        
        Returns:
            是否成功点击
        """
        location = self.locate_image(image_path, confidence)
        if location:
            center = pyautogui.center(location)
            self.click(center[0], center[1], button=button)
            return True
        return False
    
    def ocr_text(self, region: Optional[tuple] = None, lang: str = 'chi_sim+eng') -> str:
        """
        OCR 识别屏幕文字
        
        Args:
            region: 识别区域 (left, top, width, height)
            lang: 语言代码 ('eng', 'chi_sim', 'chi_sim+eng')
        
        Returns:
            识别的文字
        """
        if not HAS_PYTESSERACT:
            logger.error("pytesseract not installed")
            return ""
        
        logger.debug(f"OCR text recognition (region={region}, lang={lang})")
        screenshot = pyautogui.screenshot(region=region)
        text = pytesseract.image_to_string(screenshot, lang=lang)
        logger.info(f"OCR result: {text[:100]}...")
        return text
    
    def wait_for_image(self, image_path: str, timeout: float = 10.0, confidence: float = 0.8) -> bool:
        """
        等待图片出现
        
        Args:
            image_path: 图片路径
            timeout: 超时时间（秒）
            confidence: 匹配置信度
        
        Returns:
            是否找到图片
        """
        logger.debug(f"Waiting for image: {image_path} (timeout={timeout}s)")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.locate_image(image_path, confidence):
                return True
            time.sleep(0.5)
        
        logger.warning(f"Timeout waiting for image: {image_path}")
        return False


# 工具函数（供 nanobot 工具系统调用）

def gui_click(x: int, y: int, button: str = 'left') -> str:
    """点击指定位置"""
    try:
        controller = GUIInputControl()
        controller.click(x, y, button=button)
        return f"Clicked at ({x}, {y}) with {button} button"
    except Exception as e:
        return f"Error: {e}"


def gui_type(text: str) -> str:
    """输入文字"""
    try:
        controller = GUIInputControl()
        controller.type_text(text)
        return f"Typed: {text[:50]}..."
    except Exception as e:
        return f"Error: {e}"


def gui_hotkey(*keys: str) -> str:
    """按快捷键"""
    try:
        controller = GUIInputControl()
        controller.hotkey(*keys)
        return f"Pressed hotkey: {'+'.join(keys)}"
    except Exception as e:
        return f"Error: {e}"


def gui_screenshot(filename: str = 'screenshot.png') -> str:
    """截图"""
    try:
        controller = GUIInputControl()
        controller.screenshot(filename)
        return f"Screenshot saved to {filename}"
    except Exception as e:
        return f"Error: {e}"


def gui_ocr(region: Optional[str] = None, lang: str = 'chi_sim+eng') -> str:
    """OCR 识别"""
    try:
        controller = GUIInputControl()
        region_tuple = None
        if region:
            region_tuple = tuple(map(int, region.split(',')))
        text = controller.ocr_text(region=region_tuple, lang=lang)
        return f"OCR Result:\n{text}"
    except Exception as e:
        return f"Error: {e}"


def gui_find_image(image_path: str, confidence: float = 0.8) -> str:
    """查找图片位置"""
    try:
        controller = GUIInputControl()
        location = controller.locate_image(image_path, confidence)
        if location:
            center = pyautogui.center(location)
            return f"Found at: {location}, center: {center}"
        return "Image not found on screen"
    except Exception as e:
        return f"Error: {e}"


def gui_click_image(image_path: str, confidence: float = 0.8) -> str:
    """查找并点击图片"""
    try:
        controller = GUIInputControl()
        if controller.click_image(image_path, confidence):
            return f"Clicked image: {image_path}"
        return "Image not found, click failed"
    except Exception as e:
        return f"Error: {e}"
