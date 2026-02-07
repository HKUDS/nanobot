# PaddleOCR 文字识别功能规范

## Purpose

为 nanobot 添加基于百度 PaddleOCR 服务的图片和 PDF 文字识别（OCR）能力，实现自动化文字提取、批量处理和灵活配置。

## Requirements

### Requirement: 配置管理

系统 SHALL 支持 PaddleOCR token 和 API URL 的灵活配置，确保安全性和可定制性。

#### Scenario: 环境变量配置

- **WHEN** 环境变量 `PADDLEOCR_TOKEN` 已设置
- **THEN** 系统使用该环境变量作为 token
- **AND** 该配置具有最高优先级
- **AND** 覆盖 config.json 中的相同配置

#### Scenario: 配置文件配置

- **WHEN** `~/.nanobot/config.json` 文件中存在 `paddleocr` 配置项
- **THEN** 系统从配置文件读取 `paddleocr.token` 和 `paddleocr.apiUrl`
- **AND** 该配置优先级为中等（低于环境变量）
- **AND** 配置文件缺失时不报错（使用默认 API URL）

#### Scenario: 配置验证

- **WHEN** 系统启动或执行 OCR 脚本时
- **THEN** 系统验证 token 已配置
- **AND** 如果未配置，输出清晰的错误消息和配置指导
- **AND** 提示用户设置环境变量或修改 config.json
- **AND** 退出脚本并返回非零状态码

---

### Requirement: 文件类型检测

系统 SHALL 自动检测输入文件的类型，正确设置 API 调用的 `fileType` 参数。

#### Scenario: PDF 文档检测

- **WHEN** 输入文件的扩展名为 `.pdf`（不区分大小写）
- **THEN** 系统设置 `fileType = 0`
- **AND** 调用 PaddleOCR 的文档解析接口
- **AND** 支持 PDF 的多页结构化输出

#### Scenario: 图片文件检测

- **WHEN** 输入文件的扩展名为 `.png`、`.jpg`、`.jpeg`、`.bmp`、`.gif` 或 `.tiff`
- **THEN** 系统设置 `fileType = 1`
- **AND** 调用 PaddleOCR 的图片识别接口
- **AND** 支持单图或多图结构化输出

#### Scenario: 不支持的文件类型

- **WHEN** 输入文件的扩展名不在支持的列表中
- **THEN** 系统输出错误消息，说明支持的格式
- **AND** 跳过该文件并继续处理其他文件（批量场景）
- **AND** 在最终汇总中报告跳过的文件数量

---

### Requirement: Base64 编码

系统 SHALL 将输入文件编码为 Base64 格式，以便通过 HTTP JSON 请求上传到 PaddleOCR API。

#### Scenario: 文件读取成功

- **WHEN** 文件存在且可读
- **THEN** 系统以二进制模式读取文件内容
- **AND** 使用 base64.b64encode 编码
- **AND** 转换为 ASCII 字符串
- **AND** 确保编码后的字符串格式正确

#### Scenario: 文件读取失败

- **WHEN** 文件不存在、权限不足或读取时发生 I/O 错误
- **THEN** 系统输出错误消息，包含文件路径和错误原因
- **AND** 跳过该文件（批量场景）
- **AND** 不中断其他文件的处理

---

### Requirement: API 调用

系统 SHALL 通过 HTTPS POST 请求调用 PaddleOCR layout-parsing API，传递编码后的文件和类型参数。

#### Scenario: 成功的 API 调用

- **WHEN** API 请求成功且返回 HTTP 200 状态码
- **THEN** 系统解析 JSON 响应体
- **AND** 提取 `result.layoutParsingResults` 字段
- **AND** 继续处理和保存结果
- **AND** 显示处理成功的消息

#### Scenario: API 认证失败

- **WHEN** API 返回 HTTP 401 状态码
- **THEN** 系统输出认证错误消息
- **AND** 提示用户检查 token 是否正确或已过期
- **AND** 指引用配置文档中的 token 配置方法
- **AND** 不保存部分结果

#### Scenario: API 调用失败（非认证错误）

- **WHEN** API 返回 4xx 或 5xx 状态码（非 401）
- **THEN** 系统输出错误消息，包含状态码和响应前 200 字符
- **AND** 跳过当前文件的处理
- **AND** 不影响其他文件的批量处理

#### Scenario: 网络超时或连接失败

- **WHEN** 请求在 60 秒内未完成或网络不可达
- **THEN** 系统捕获 `requests.exceptions.RequestException`
- **THEN** 输出网络错误消息，包含异常详情
- **AND** 建议用户检查网络连接和 API 可用性
- **AND** 跳过当前文件

#### Scenario: JSON 响应解析失败

- **WHEN** API 响应体不是有效的 JSON 格式
- **THEN** 系统捕获 `json.JSONDecodeError`
- **THEN** 输出解析错误消息和原始响应
- **AND** 跳过当前文件

---

### Requirement: 批量处理

系统 SHALL 支持单次命令处理多个文件，提升批量场景的效率。

#### Scenario: 多文件输入

- **WHEN** 用户在命令行提供多个文件路径或使用通配符展开
- **THEN** 系统顺序处理每个文件
- **AND** 为每个文件独立调用 OCR API
- **AND** 任何单个文件失败不中断其他文件的处理
- **AND** 在最终汇总中显示成功和失败的数量

#### Scenario: 通配符支持

- **WHEN** 用户使用 shell 通配符（如 `*.png`）
- **THEN** 系统依赖 shell 展开通配符为多个文件路径
- **AND** 处理展开后的所有匹配文件
- **AND** 不自行执行通配符匹配逻辑

#### Scenario: 进度反馈

- **WHEN** 处理多个文件时
- **THEN** 系统显示每个文件的处理状态
- **AND** 显示 "✓ 保存: 文件名" 表示成功
- **AND** 显示 "ERROR: 失败原因" 表示失败
- **AND** 在完成后显示汇总统计（总文档数）

---

### Requirement: 结果保存

系统 SHALL 将 OCR 识别结果保存为 Markdown 文件，并下载识别结果中包含的关联图片。

#### Scenario: 保存 Markdown 文件

- **WHEN** API 返回识别结果
- **THEN** 系统将 `layoutParsingResults` 中的每个元素保存为独立文件
- **AND** 文件命名格式为 `doc_<全局索引>_<页面索引>.md`
- **AND** 保存路径为 `~/.nanobot/workspace/output/`
- **AND** 输出目录不存在时自动创建
- **AND** 使用 UTF-8 编码写入文件

#### Scenario: 保存关联图片

- **WHEN** 识别结果中的 `markdown.images` 字段包含图片 URL
- **THEN** 系统下载每个图片到输出目录
- **AND** 保存文件名为图片原始名称
- **AND** 设置 HTTP 请求超时为 30 秒
- **AND** 下载成功时显示 "└─ Image: 文件路径"

#### Scenario: 图片下载失败

- **WHEN** 图片下载返回非 200 状态码或网络错误
- **THEN** 系统输出警告消息（WARNING）
- **AND** 继续处理其他图片和文件
- **AND** 不中断整体流程

#### Scenario: 自定义输出目录

- **WHEN** 用户通过 `--output` 参数指定输出目录
- **THEN** 系统使用指定目录替代默认的 `~/.nanobot/workspace/output/`
- **AND** 自动创建不存在的目录
- **AND** 所有文件输出到该目录

---

### Requirement: 可选参数配置

系统 SHALL 支持高级 OCR 参数的配置，默认禁用以优化处理速度。

#### Scenario: 默认参数设置

- **WHEN** 调用 PaddleOCR API 时
- **THEN** 系统发送以下可选参数为 `False`
  - `useDocOrientationClassify`：文档方向分类
  - `useDocUnwarping`：文档去畸变
  - `useChartRecognition`：图表识别
- **AND** 这些参数默认值确保快速处理

#### Scenario: 参数自定义（代码修改）

- **WHEN** 用户需要启用高级功能（需修改脚本代码）
- **THEN** 脚本中提供清晰的参数位置
- **AND** 可修改 `payload` 字典中的对应值
- **AND** 文档中说明每个参数的作用和影响

---

### Requirement: 错误处理和用户指导

系统 SHALL 提供清晰的错误消息和解决方案指导，提升用户体验。

#### Scenario: 配置缺失指导

- **WHEN** 检测到未配置 token
- **THEN** 输出多行错误说明
- **AND** 包含方法一：环境变量配置示例（`export PADDLEOCR_TOKEN="..."`）
- **AND** 包含方法二：config.json 配置示例（JSON 片段）
- **AND** 退出并返回非零状态码

#### Scenario: 文件路径错误

- **WHEN** 输入文件路径不存在
- **THEN** 输出 "ERROR: File not found: 文件路径"
- **THEN** 跳过该文件
- **AND** 在批量处理中继续其他文件

#### Scenario: API 服务不可用

- **WHEN** 连续多次调用失败（网络超时或 5xx 错误）
- **THEN** 在错误消息中提示用户检查网络连接
- **AND** 建议用户验证 API URL 的可访问性
- **AND** 提供故障排查文档参考

---

### Requirement: Skill 元数据规范

系统 SHALL 遵循 nanobot skill 的标准格式，确保 SkillsLoader 能够正确加载和发现。

#### Scenario: YAML Frontmatter 格式

- **WHEN** 创建 SKILL.md 文件
- **THEN** 包含以下 YAML frontmatter 字段：
  - `name`: 技能名称（kebab-case，如 "paddleocr"）
  - `description`: 技能描述，明确触发场景
  - `metadata.nanobot.emoji`: 技能图标（如 "🔍"）
  - `metadata.nanobot.requires.bins`: 依赖的 CLI 工具（如 `["python3"]`）
  - `metadata.nanobot.requires.env`: 需要的环境变量（如 `["PADDLEOCR_TOKEN"]`）
  - `homepage`: 可选的服务主页链接
- **AND** frontmatter 和正文之间使用 `---` 分隔符

#### Scenario: Skill 触发描述

- **WHEN** 编写 `description` 字段
- **THEN** 明确列出触发技能的用户意图
- **AND** 包括但不限于：
  - "Extract text from images"
  - "Recognize text from screenshots"
  - "Convert images/PDFs to Markdown"
  - "Perform OCR on document images"
  - "Batch process multiple files"

#### Scenario: Skill 内容组织

- **WHEN** 编写 SKILL.md 的正文
- **THEN** 包含以下章节：
  - Configuration（配置说明）
  - Quick Start（快速开始）
  - How It Works（工作原理）
  - Output Structure（输出结构）
  - Supported File Types（支持的文件类型）
  - Troubleshooting（故障排查）
  - Advanced Parameters（高级参数，可选）
- **AND** 使用代码块和表格展示示例
- **AND** 保持简洁，避免冗余说明

---

### Requirement: 依赖和构建集成

系统 SHALL 正确配置项目依赖和构建规则，确保 skill 被正确打包和分发。

#### Scenario: requests 依赖

- **WHEN** 用户安装或打包 nanobot
- **THEN** `requests>=2.0.0` 库被自动安装
- **AND** 脚本可以导入 `requests` 模块
- **AND** API 调用功能可用

#### Scenario: 构建规则配置

- **WHEN** hatchling 打包 wheel 或 sdist
- **THEN** 构建配置包含 `nanobot/skills/**/*.py` 模式
- **AND** 脚本文件被包含在分发包中
- **AND** 用户安装后脚本位于正确的路径

#### Scenario: Skills README 更新

- **WHEN** 项目发布或用户查看可用 skills
- **THEN** `nanobot/skills/README.md` 包含 paddleocr 条目
- **AND** 描述为 "OCR image and PDF recognition using PaddleOCR service"
- **AND** 列表格式与其他 skills 保持一致

---

### Requirement: 安全性

系统 SHALL 确保敏感信息的安全存储和传输。

#### Scenario: Token 不硬编码

- **WHEN** 实现配置加载逻辑
- **THEN** 代码中不包含真实的 token 值
- **AND** 仅保留 API URL 的默认值（非敏感信息）
- **AND** 强制用户通过环境变量或配置文件提供 token

#### Scenario: 配置文件安全

- **WHEN** 用户提供 config.json 示例
- **THEN** 文档明确建议将 `config.json` 添加到 `.gitignore`
- **AND** 推荐使用环境变量存储 token（更高优先级）
- **AND** 避免意外提交敏感信息到版本控制
