---
name: paddleocr
description: "OCR image and PDF recognition using PaddleOCR. Use when user asks to: (1) Extract text from images, (2) Recognize text from screenshots, (3) Convert images/PDFs to Markdown, (4) Perform OCR on document images, (5) Batch process multiple files"
metadata: {
  "nanobot": {
    "emoji": "🔍",
    "requires": {
      "bins": ["python3"],
      "env": ["PADDLEOCR_TOKEN"]
    }
  }
}
homepage: https://aistudio.baidu.com/app/overview
---

# PaddleOCR

强大的 OCR 服务，支持图片和 PDF 文档的文字识别、批量处理和灵活配置。


## Configuration

### API Token（必需）

**必须配置 PaddleOCR token** 才能使用此 skill。

**方式 1：环境变量**（推荐用于生产环境）
```bash
export PADDLEOCR_TOKEN="your-token-here"
```

**方式 2：配置文件**
添加到 `~/.nanobot/config.json`:
```json
{
  "paddleocr": {
    "token": "your-token-here",
    "apiUrl": "https://your-custom-url.com/layout-parsing"
  }
}
```

**优先级**：环境变量 `PADDLEOCR_TOKEN` > 配置文件 > 默认值

### API URL

默认：`https://k7b3acgclfxeacxe.aistudio-app.com/layout-parsing`

可通过 `config.json["paddleocr"]["apiUrl"]` 自定义。


## Quick Start

### 单个文件

```bash
# 识别图片
python3 ~/.nanobot/workspace/skills/paddleocr/scripts/ocr.py /path/to/image.png

# 处理 PDF 文档
python3 ~/.nanobot/workspace/skills/paddleocr/scripts/ocr.py /path/to/document.pdf
```

### 批量处理

```bash
# 处理多个文件
python3 ~/.nanobot/workspace/skills/paddleocr/scripts/ocr.py img1.png img2.jpg img3.png

# 处理所有 PNG 文件（shell 展开通配符）
python3 ~/.nanobot/workspace/skills/paddleocr/scripts/ocr.py ~/Downloads/*.png

# 自定义输出目录用于批量处理
python3 ~/.nanobot/workspace/skills/paddleocr/scripts/ocr.py ~/Documents/*.png --output ~/results/
```


## Output Structure

识别结果统一保存到：`~/.nanobot/workspace/output/` 目录。

**文件命名**：
- Markdown 文件：`doc_{全局索引}_{页面索引}.md`
- 提取的图片：使用原始文件名

**示例结构**：
```
output/
├── doc_0_0.md          # 第一个文件的第 1 个结果
├── extracted_image.png    # 从第一个结果中提取的图片
├── doc_1_0.md          # 第二个文件
└── ...
```


## Supported File Types

| 类型 | 扩展名 | fileType |
|-----|--------|----------|
| 图片 | .png, .jpg, .jpeg, .bmp, .gif, .tiff | 1 |
| 文档 | .pdf | 0 |

**说明**：系统自动检测文件类型并设置正确的 API 参数。


## Troubleshooting

### Token 未配置

```
ERROR: PaddleOCR token not configured
```

**解决方案**：设置 token via 环境变量或 config.json（参见 Configuration 章节）

### API 认证失败

```
ERROR: API request failed with status 401
```

**解决方案**：
- 验证 token 是否正确
- 检查 token 是否已过期
- 确保 token 匹配 PaddleOCR 服务

### 网络错误

```
ERROR: Failed to call API: Connection timeout
```

**解决方案**：
- 检查网络连接
- 验证 API URL 可访问性
- 稍后重试

### 空输出

如果输出 Markdown 文件为空：
- 文件可能已损坏或格式不支持
- 检查 API 服务是否正常运行
- 尝试使用 PNG 格式（推荐）


## How It Works

### 工作流程

1. **文件类型检测**：根据文件扩展名自动设置 API 的 `fileType` 参数（PDF=0, 图片=1）
2. **Base64 编码**：将文件内容编码为 base64 格式
3. **API 调用**：通过 HTTPS POST 请求调用 PaddleOCR layout-parsing API
4. **结果解析**：解析 JSON 响应体，提取 `layoutParsingResults` 字段
5. **结果保存**：将 Markdown 文本和关联图片保存到输出目录

### 批量处理支持

支持单次命令处理多个文件，每个文件独立调用 API，失败不中断其他文件。


## Output Structure

识别结果统一保存到：`~/.nanobot/workspace/output/` 目录。

**文件命名**：
- Markdown 文件：`doc_{全局索引}_{页面索引}.md`
- 提取的图片：使用原始文件名

**示例结构**：
```
output/
├── doc_0_0.md          # 第一个文件的第 1 个结果
├── extracted_image.png    # 从第一个结果中提取的图片
├── doc_1_0.md          # 第二个文件
└── ...
```
