---
name: image-ocr
description: 图片OCR识别Skill - 提取图片中的文字，供纯文本模型使用
---
# Image OCR Skill

将图片中的文字提取出来，让不支持视觉的模型（如 Qwen-Coder）也能"看懂"图片内容。

## 核心能力

- 🖼️ 支持多种图片格式（PNG、JPG、WEBP、GIF）
- 🔤 中英文混合识别
- 💻 代码截图专用优化
- 📊 表格/结构化数据提取

## 快速开始

### 1. 安装依赖

```bash
# 安装 PaddleOCR（首次使用需要）
pip3 install paddleocr -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或安装轻量版（推荐，模型更小）
pip3 install paddlepaddle paddleocr
```

### 2. 配置（可选）

编辑 `config.json`：
```json
{
  "ocr_engine": "paddle",  // paddle | baidu | tencent
  "baidu_api_key": "your_key",
  "baidu_secret_key": "your_secret",
  "language": "ch_sim",  // ch_sim | en | ch_tra
  "save_temp": false     // 是否保存临时文件
}
```

### 3. 使用

```bash
# 命令行
python3 skills/image-ocr/scripts/ocr.py /path/to/image.png

# 带选项
python3 skills/image-ocr/scripts/ocr.py /path/to/image.png --format markdown --save
```

## 在 OpenClaw 中集成

### 方案A：图片自动转文字（推荐）

修改你的 Agent 配置，在收到图片消息时自动调用 OCR：

```python
# 在消息处理逻辑中添加
if message.type == "image":
    # 下载图片
    image_path = download_image(message.file_key)
    
    # OCR提取文字
    ocr_result = run_skill("image-ocr", image_path)
    
    # 把文字喂给 Qwen-Coder
    text_prompt = f"用户发了一张图片，内容是：\n{ocr_result}\n请根据以上内容回答..."
    response = query_model("qwen-coder", text_prompt)
```

### 方案B：显式调用

用户主动要求识别图片：

```
用户：帮我识别这张图里的代码
[图片]
🦞：我来识别一下...
[调用 ocr skill]
🦞：图片里的代码是：...
```

## 输出格式

### 默认格式（纯文本）
```
这是图片中的文字内容：
第一行文字
第二行文字
第三行文字
```

### Markdown 格式（--format markdown）
```markdown
## 图片内容识别结果

```python
def hello():
    print("Hello World")
```

表格数据：
| 列1 | 列2 |
|-----|-----|
| A   | B   |
```

### JSON 格式（--format json）
```json
{
  "text": "完整文字",
  "blocks": [
    {"text": "第一块", "confidence": 0.98, "position": [x1,y1,x2,y2]},
    {"text": "第二块", "confidence": 0.95, "position": [x1,y1,x2,y2]}
  ],
  "language": "ch_sim"
}
```

## 代码截图优化

针对代码截图的特殊处理：

```python
# 自动检测代码并格式化
ocr_result = ocr.recognize(image_path)
if is_code_screenshot(ocr_result):
    formatted = format_as_code(ocr_result)
```

特性：
- 自动检测缩进
- 修复OCR常见的符号错误（`0`→`O`，`1`→`l`）
- 识别代码语言（Python、JS、Java等）

## 文件结构

```
skills/image-ocr/
├── SKILL.md
├── config.json           # 配置文件
├── ocr_engine.py         # OCR引擎封装
├── post_processor.py     # 后处理（代码格式化等）
└── scripts/
    └── ocr.py           # CLI入口
```

## 常见问题

**Q: PaddleOCR 安装失败？**
```bash
# 使用 Conda 安装（解决依赖冲突）
conda install paddlepaddle -c conda-forge
pip install paddleocr
```

**Q: 识别准确率不高？**
- 检查图片清晰度（建议300dpi以上）
- 尝试不同的 `language` 配置
- 对于手写体，建议使用百度/腾讯OCR API

**Q: 支持多语言吗？**
- PaddleOCR 默认支持中英，可扩展日韩等
- 百度/腾讯API支持更多语言

## 更新记录

- **v1.0** (2026-02-11): 初始版本，支持 PaddleOCR 和百度OCR
