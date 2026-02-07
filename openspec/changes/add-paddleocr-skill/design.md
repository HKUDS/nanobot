## Context

nanobot当前支持多种内置skills（github、weather、summarize、tmux等），每个skill通过SKILL.md文件提供agent的扩展能力。SkillsLoader负责扫描`nanobot/skills/`和`~/.nanobot/workspace/skills/`目录，自动发现并加载skill元数据和内容。

当前nanobot缺乏OCR（光学字符识别）能力，无法处理图片文字提取、截图识别和PDF文档解析等场景。用户需要在agent之外单独使用OCR工具，降低了工作流程的集成度。

百度PaddleOCR提供了基于AI的强大OCR服务，支持图片和PDF文档的布局解析和文字识别。该服务通过REST API提供，使用token认证，返回结构化的Markdown文本和关联图片。

**约束条件**：
- Skill必须作为内置skill集成到`nanobot/skills/`目录
- 需要处理配置优先级：环境变量 > config.json > 默认值
- 支持批量处理多个文件（用户常见场景）
- 输出路径固定为`~/.nanobot/workspace/output/`
- 必须添加`requests`库作为项目依赖
- 构建系统需要包含skill目录下的Python脚本

## Goals / Non-Goals

**Goals:**
1. 添加PaddleOCR内置skill，使agent能够识别图片和PDF中的文字
2. 提供可独立执行的Python脚本，支持批量处理多个文件
3. 支持灵活的配置方式（环境变量、config.json）
4. 自动检测文件类型（PDF vs 图片）并设置正确的API参数
5. 保存识别结果为Markdown格式，并下载关联图片
6. 遵循nanobot skill的标准格式和规范

**Non-Goals:**
1. 不实现实时视频帧OCR
2. 不提供GUI界面或Web UI
3. 不支持OCR结果的手动编辑或后处理
4. 不集成到agent tool系统（作为bash工具调用脚本）
5. 不添加日志调试功能（保持简洁）

## Decisions

### 1. 脚本独立性

**决策**：将PaddleOCR功能封装为独立的Python CLI脚本，而非集成到agent tool系统。

**理由**：
- 降低耦合度，脚本可独立运行和测试
- 避免增加agent主代码的复杂度
- 用户可直接在命令行使用，不限于agent场景
- 符合现有skills的设计模式（如github skill使用gh CLI）

**备选方案**：
- 创建`PaddleOCRTool`类继承`Tool`基类，注册到ToolRegistry
  - 优点：完全集成到agent，agent可直接调用
  - 缺点：增加代码量，需要异步适配，脚本可复用性降低

### 2. 配置优先级策略

**决策**：配置加载优先级为 环境变量 > config.json > 代码默认值（仅API URL有默认值）。

**理由**：
- 环境变量提供最高灵活性，便于CI/CD和临时配置
- config.json提供持久化配置，适合日常使用
- 代码默认值仅用于API URL（固定的生产地址）
- 不保留默认token值，确保安全性（用户必须显式配置）

**实现方式**：
```python
config = load_config_json()
token = os.environ.get("PADDLEOCR_TOKEN") or config.get("token")
if not token:
    error("未配置PaddleOCR token")
api_url = config.get("apiUrl", DEFAULT_API_URL)
```

### 3. 批量处理设计

**决策**：脚本支持多文件参数，使用`argparse`的`nargs='+'`。

**理由**：
- 用户常见场景是处理多个图片（如批量截图）
- shell通配符展开后可直接传递多个文件
- 简化使用，无需循环调用脚本

**实现示例**：
```bash
# 单文件
python3 ocr.py img.png

# 多文件
python3 ocr.py img1.png img2.jpg img3.png

# 通配符
python3 ocr.py ~/Downloads/*.png
```

### 4. 文件类型自动检测

**决策**：根据文件扩展名自动设置`fileType`参数（PDF=0, 图片=1）。

**理由**：
- 避免用户手动指定文件类型
- 降低使用错误率
- 支持常见图片格式（PNG、JPG、JPEG、BMP、GIF、TIFF）

**检测逻辑**：
```python
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff'}
def detect_file_type(file_path):
    return 0 if Path(file_path).suffix.lower() == '.pdf' else 1
```

### 5. 输出目录固定化

**决策**：输出目录固定为`~/.nanobot/workspace/output/`，可通过`--output`参数覆盖。

**理由**：
- 与nanobot的workspace设计保持一致
- 便于结果管理和清理
- 提供可选的输出目录参数，支持灵活场景

### 6. 依赖管理

**决策**：在`pyproject.toml`中添加`requests>=2.0.0`，并更新构建规则包含`nanobot/skills/**/*.py`。

**理由**：
- 确保安装时自动安装requests库
- Python脚本被正确打包到wheel中
- 符合hatchling构建系统的规范

**修改内容**：
```toml
dependencies = [
    # ...现有依赖...
    "requests>=2.0.0",
]

[tool.hatch.build]
include = [
    "nanobot/**/*.py",
    "nanobot/skills/**/*.md",
    "nanobot/skills/**/*.sh",
    "nanobot/skills/**/*.py",  # 新增
]
```

### 7. 错误处理和用户提示

**决策**：提供清晰的错误消息和配置指导，而非技术性异常堆栈。

**理由**：
- 提升用户体验，便于快速定位问题
- 降低使用门槛
- 遵循CLI工具的最佳实践

**错误场景**：
- 未配置token：提示配置方法（环境变量 + config.json示例）
- 文件不存在：提示检查路径
- API调用失败：显示状态码和响应前200字符
- 保存失败：提示检查目录权限

## Risks / Trade-offs

### 风险1：API服务依赖

**风险**：PaddleOCR API服务不可用或限流时，skill将完全失效。

**缓解措施**：
- 文档中提供故障排查指南（网络、认证、服务状态）
- 建议用户检查API URL可访问性
- 在脚本中设置合理超时（60秒）

### 风险2：Token安全性

**风险**：将token存储在config.json中可能被意外提交到版本控制。

**缓解措施**：
- 在README中明确说明`.gitignore`应包含`config.json`
- 优先推荐使用环境变量
- 文档中不包含实际token值，仅使用占位符

### 风险3：批量处理的资源占用

**风险**：同时处理多个大文件可能导致内存和临时文件占用过高。

**缓解措施**：
- 串行处理每个文件（非并行），避免资源竞争
- API超时限制为60秒
- 文档中建议分批处理大量文件

### 权衡：简洁 vs 功能

**权衡**：不添加日志/verbose参数以保持代码简洁，但调试时可能受限。

**理由**：
- 根据用户反馈"先不加"，明确不在v1中实现
- 大多数场景不需要详细日志，错误信息已足够
- 未来可根据需求扩展

### 权衡：默认值 vs 强制配置

**权衡**：不保留token默认值，强制用户配置。

**理由**：
- 安全性：避免token泄露到代码仓库
- 明确性：强制用户主动配置，减少误用
- 符合最佳实践：敏感信息不硬编码

---

## Open Questions

1. 是否需要支持API调用的重试机制？（当前设计中单次调用，失败即退出）
2. 批量处理时是否需要进度显示？（当前设计显示每个文件的处理结果）
3. 是否需要支持自定义API超时时间？（当前固定60秒）
