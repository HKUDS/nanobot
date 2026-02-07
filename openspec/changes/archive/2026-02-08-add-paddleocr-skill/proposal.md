## Why

用户需要从图片和PDF文档中提取文字内容。当前nanobot系统缺乏内置的OCR（光学字符识别）能力，限制了agent在处理图片、截图和文档时的实用性。通过添加PaddleOCR skill，agent将能够识别图像中的文字，支持批量处理多个文件，大幅扩展其在文档理解和内容提取方面的能力。

## What Changes

- 在`nanobot/skills/`目录下新增`paddleocr`内置skill
- 新增`nanobot/skills/paddleocr/SKILL.md`文档，包含完整的skill说明和使用指南
- 新增`nanobot/skills/paddleocr/scripts/ocr.py`脚本，封装PaddleOCR API调用逻辑
- 在`pyproject.toml`中添加`requests>=2.0.0`依赖
- 更新`pyproject.toml`的构建规则，包含`nanobot/skills/**/*.py`文件
- 更新`nanobot/skills/README.md`，添加paddleocr skill说明
- 支持**批量处理**：单次命令处理多个图片/PDF文件
- 支持**配置化**：通过环境变量或config.json配置API token和URL
- 输出结果到`~/.nanobot/workspace/output/`目录，保存Markdown和提取的图片

## Capabilities

### New Capabilities

- `paddleocr-ocr`: 提供基于PaddleOCR服务的图片和PDF文字识别能力。支持图片（PNG、JPG、JPEG等）和PDF文档的OCR识别，能够批量处理多个文件，自动检测文件类型并调用相应的API接口，将识别结果保存为Markdown格式并下载关联图片。

### Modified Capabilities

无现有capability的需求变更。仅添加新的内置skill，不修改现有spec级别的行为。

## Impact

- **新增技能文件**：`nanobot/skills/paddleocr/`目录及其子目录和文件
- **依赖变更**：在项目依赖中添加`requests>=2.0.0`
- **构建系统变更**：更新打包配置以支持skill目录下的Python脚本
- **技能系统扩展**：SkillsLoader将自动发现并加载paddleocr skill，agent能够触发该skill的执行
- **API集成**：通过HTTPS POST调用百度PaddleOCR服务（默认API URL: https://k7b3acgclfxeacxe.aistudio-app.com/layout-parsing）
- **配置管理**：支持环境变量`PADDLEOCR_TOKEN`和`~/.nanobot/config.json`中的配置项，优先级为环境变量 > 配置文件
- **输出管理**：识别结果统一输出到用户workspace的output目录
