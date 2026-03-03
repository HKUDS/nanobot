# Skill: GUI Input Control (图形界面输入控制)

## 描述
提供系统级鼠标、键盘控制和屏幕内容分析能力，适用于 WSL + WSLg 环境和 Linux 桌面环境。

## 技术栈
- **鼠标键盘控制**: `pyautogui` (跨平台) / `xdotool` (X11)
- **屏幕截图**: `pyautogui` / `PIL`
- **OCR 文字识别**: `pytesseract` + `tesseract-ocr`
- **图像定位**: `pyautogui.locateOnScreen`

## 安装依赖

```bash
# 系统工具
sudo apt install -y xdotool scrot maim tesseract-ocr tesseract-ocr-chi-sim

# Python 依赖
pip install pyautogui pillow pytesseract
```

## 环境变量

WSL 环境需要设置：
```bash
export DISPLAY=:0
```

## API 接口

### 鼠标控制

```python
import pyautogui

# 移动鼠标
pyautogui.moveTo(x, y, duration=0.5)  # 平滑移动到坐标
pyautogui.moveRel(x_offset, y_offset)  # 相对移动

# 点击
pyautogui.click(x, y, button='left')    # 左键点击
pyautogui.doubleClick(x, y)             # 双击
pyautogui.rightClick(x, y)              # 右键点击
pyautogui.mouseDown(button='left')      # 按住
pyautogui.mouseUp(button='left')        # 松开

# 拖拽
pyautogui.dragTo(x, y, duration=0.5)
pyautogui.dragRel(x_offset, y_offset)
```

### 键盘控制

```python
import pyautogui

# 输入文字
pyautogui.write('Hello World', interval=0.1)  # interval 是按键间隔

# 按键
pyautogui.press('enter')           # 单键
pyautogui.press(['up', 'up', 'down'])  # 多键
pyautogui.keyDown('shift')         # 按住
pyautogui.keyUp('shift')           # 松开

# 快捷键
pyautogui.hotkey('ctrl', 'c')      # Ctrl+C
pyautogui.hotkey('ctrl', 'shift', 'n')  # 多键组合
```

### 屏幕截图与分析

```python
import pyautogui
from PIL import Image

# 截图
screenshot = pyautogui.screenshot()
screenshot.save('screen.png')

# 区域截图
region = pyautogui.screenshot(region=(x, y, width, height))

# 获取像素颜色
pixel = pyautogui.pixel(x, y)
pixel_rgb = pyautogui.pixelMatchesColor(x, y, (255, 0, 0))

# 屏幕尺寸
width, height = pyautogui.size()
current_x, current_y = pyautogui.position()
```

### OCR 文字识别

```python
import pytesseract
from PIL import Image

# 识别截图文字
screenshot = pyautogui.screenshot()
text = pytesseract.image_to_string(screenshot, lang='chi_sim+eng')

# 识别区域文字
region = pyautogui.screenshot(region=(100, 100, 300, 200))
text = pytesseract.image_to_string(region, lang='eng')

# 识别配置
custom_config = r'--oem 3 --psm 6'
text = pytesseract.image_to_string(screenshot, config=custom_config)
```

### 图像定位与识别

```python
import pyautogui

# 查找图片位置
location = pyautogui.locateOnScreen('button.png', confidence=0.8)
if location:
    center = pyautogui.center(location)
    pyautogui.click(center)

# 查找所有匹配位置
locations = pyautogui.locateAllOnScreen('icon.png')
for loc in locations:
    print(f"找到位置：{loc}")

# 截取定位区域
if location:
    button_image = pyautogui.screenshot(region=location)
```

## 安全设置

```python
import pyautogui

# 启用故障保护（鼠标移到左上角触发异常）
pyautogui.FAILSAFE = True

# 设置操作间隔（防止过快）
pyautogui.PAUSE = 0.5  # 每次操作后等待 0.5 秒
```

## 使用示例

### 示例 1：打开浏览器并访问网址

```python
import pyautogui
import time

pyautogui.PAUSE = 0.5

# Ctrl+L 聚焦地址栏
pyautogui.hotkey('ctrl', 'l')
time.sleep(0.3)

# 输入网址
pyautogui.write('https://github.com')
time.sleep(0.3)

# 回车
pyautogui.press('enter')
```

### 示例 2：截图并识别文字

```python
import pyautogui
import pytesseract

# 截图
screenshot = pyautogui.screenshot()
screenshot.save('capture.png')

# OCR 识别
text = pytesseract.image_to_string(screenshot, lang='chi_sim+eng')
print(f"识别文字：{text}")
```

### 示例 3：查找并点击按钮

```python
import pyautogui

# 查找按钮图片
button_loc = pyautogui.locateOnScreen('submit_button.png', confidence=0.9)

if button_loc:
    # 点击按钮中心
    center = pyautogui.center(button_loc)
    pyautogui.click(center)
    print(f"已点击按钮：{center}")
else:
    print("未找到按钮")
```

### 示例 4：自动化表单填写

```python
import pyautogui
import time

# 移动到第一个输入框
pyautogui.click(500, 300)
time.sleep(0.3)

# 填写内容
pyautogui.write('用户名')
pyautogui.press('tab')
time.sleep(0.3)

pyautogui.write('密码 123')
pyautogui.press('tab')
time.sleep(0.3)

pyautogui.write('email@example.com')

# 点击提交
pyautogui.click(500, 500)
```

## 注意事项

1. **WSL 环境**: 必须设置 `DISPLAY=:0` 环境变量
2. **权限**: 某些操作可能需要 root 权限
3. **屏幕缩放**: 高 DPI 屏幕可能需要调整坐标
4. **安全性**: 始终启用 `FAILSAFE` 防止失控
5. **速度**: 设置合适的 `PAUSE` 避免操作过快
6. **图像识别**: 确保截图与实际屏幕分辨率一致

## 故障排除

### 问题：xdotool 无法找到窗口
```bash
# 检查 DISPLAY 环境变量
echo $DISPLAY

# 列出所有窗口
xdotool search --name ""
```

### 问题：pyautogui 坐标不正确
```python
# 检查屏幕分辨率
import pyautogui
print(pyautogui.size())

# 获取当前鼠标位置
print(pyautogui.position())
```

### 问题：OCR 识别不准确
```python
# 尝试不同的语言配置
text = pytesseract.image_to_string(image, lang='eng')  # 英文
text = pytesseract.image_to_string(image, lang='chi_sim')  # 简体中文
text = pytesseract.image_to_string(image, lang='chi_sim+eng')  # 混合
```

## 相关文件

- 技能位置：`/mnt/d/fe/nanobot/nanobot/skills/gui-input-control/SKILL.md`
- 示例脚本：`/mnt/d/fe/nanobot/nanobot/skills/gui-input-control/examples/`
- 测试图片：`/mnt/d/fe/nanobot/nanobot/skills/gui-input-control/assets/`
