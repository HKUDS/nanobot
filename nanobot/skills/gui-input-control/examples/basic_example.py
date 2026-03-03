#!/usr/bin/env python3
"""
GUI Input Control 示例脚本

演示如何使用 GUI 控制功能自动化操作。
"""

import sys
import time
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from nanobot.skills.gui_input_control.gui_control import GUIInputControl


def example_basic_control():
    """基础控制示例"""
    print("=" * 50)
    print("示例 1: 基础鼠标键盘控制")
    print("=" * 50)
    
    controller = GUIInputControl(pause=0.5)
    
    # 获取屏幕信息
    width, height = controller.get_screen_size()
    print(f"屏幕分辨率：{width}x{height}")
    
    # 获取当前鼠标位置
    x, y = controller.get_mouse_position()
    print(f"当前鼠标位置：({x}, {y})")
    
    # 移动鼠标
    print("移动鼠标到屏幕中心...")
    controller.move_mouse(width // 2, height // 2, duration=1.0)
    time.sleep(1)
    
    # 点击
    print("左键点击...")
    controller.click()
    time.sleep(0.5)
    
    # 输入文字
    print("输入文字...")
    controller.type_text("Hello from nanobot GUI control!")
    time.sleep(0.5)
    
    # 快捷键
    print("按 Ctrl+A 全选...")
    controller.hotkey('ctrl', 'a')
    time.sleep(0.5)
    
    print("完成！\n")


def example_screenshot_ocr():
    """截图和 OCR 示例"""
    print("=" * 50)
    print("示例 2: 截图和 OCR 文字识别")
    print("=" * 50)
    
    controller = GUIInputControl(pause=0.5)
    
    # 全屏截图
    print("截取全屏...")
    screenshot_file = '/tmp/gui_example_screenshot.png'
    controller.screenshot(screenshot_file)
    print(f"截图保存到：{screenshot_file}")
    
    # OCR 识别
    print("识别屏幕文字...")
    text = controller.ocr_text(lang='chi_sim+eng')
    print(f"识别结果:\n{text[:500]}...")  # 只显示前 500 字符
    
    print("完成！\n")


def example_browser_automation():
    """浏览器自动化示例"""
    print("=" * 50)
    print("示例 3: 浏览器自动化（打开 GitHub）")
    print("=" * 50)
    
    controller = GUIInputControl(pause=0.5)
    
    # 假设浏览器已经打开
    print("请确保 Chromium 浏览器已打开...")
    time.sleep(2)
    
    # Ctrl+L 聚焦地址栏
    print("聚焦地址栏...")
    controller.hotkey('ctrl', 'l')
    time.sleep(0.5)
    
    # 输入网址
    print("输入网址...")
    controller.type_text("https://github.com/tornado404/nanobot")
    time.sleep(0.5)
    
    # 回车
    print("访问网址...")
    controller.press_key('enter')
    time.sleep(3)
    
    # 截图
    print("截图...")
    controller.screenshot('/tmp/github_page.png')
    
    print("完成！\n")


def example_image_click():
    """图像定位点击示例"""
    print("=" * 50)
    print("示例 4: 图像定位并点击")
    print("=" * 50)
    
    controller = GUIInputControl(pause=0.5)
    
    # 创建测试图片（实际使用时替换为真实图片）
    test_image = '/tmp/test_button.png'
    
    if Path(test_image).exists():
        print(f"查找图片：{test_image}")
        location = controller.locate_image(test_image, confidence=0.8)
        
        if location:
            print(f"找到图片位置：{location}")
            center = controller.get_controller().pyautogui.center(location)
            print(f"中心点：{center}")
            
            # 点击图片
            print("点击图片...")
            controller.click_image(test_image)
        else:
            print("未找到图片")
    else:
        print(f"测试图片不存在：{test_image}")
        print("提示：先截取一个按钮图片用于测试")
    
    print("完成！\n")


def main():
    """运行所有示例"""
    print("\n" + "=" * 60)
    print("nanobot GUI Input Control 示例")
    print("=" * 60 + "\n")
    
    # 检查环境
    try:
        import pyautogui
        print(f"✅ pyautogui 版本：{pyautogui.__version__}")
    except ImportError:
        print("❌ pyautogui 未安装，运行：pip install pyautogui pillow")
        return
    
    try:
        import pytesseract
        print(f"✅ pytesseract 已安装")
    except ImportError:
        print("⚠️ pytesseract 未安装，OCR 功能不可用")
    
    # 检查 DISPLAY
    import os
    display = os.environ.get('DISPLAY')
    if display:
        print(f"✅ DISPLAY 环境变量：{display}")
    else:
        print("⚠️ DISPLAY 未设置，运行：export DISPLAY=:0")
    
    print("\n")
    
    # 运行示例
    try:
        example_basic_control()
        # example_screenshot_ocr()
        # example_browser_automation()
        # example_image_click()
        
        print("=" * 60)
        print("所有示例运行完成！")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"\n错误：{e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
