---
name: feishu-doc-orchestrator
description: 飞书文档创建主编排技能 - 将 Markdown 文件转换为飞书文档，编排多个子技能协作完成，支持25种飞书文档块类型。
---

# 飞书文档创建技能 - GitHub发布版

将 Markdown 文件转换为飞书文档，支持25种块类型，完整权限管理。

## 快速开始

### 1. 配置飞书应用

首次使用需要配置飞书开放平台应用信息：

```bash
python .claude/skills/feishu-doc-orchestrator/scripts/setup_config.py
```

或手动创建配置文件 `.claude/feishu-config.env`：

```ini
# 从 https://open.feishu.cn/ 获取
FEISHU_APP_ID = "cli_xxx"
FEISHU_APP_SECRET = "xxxxxxxx"

# 可选：自动添加文档权限
FEISHU_AUTO_COLLABORATOR_ID = "ou_xxx"

# 可选：默认文件夹
FEISHU_DEFAULT_FOLDER = "folder_token"
```

### 2. 检查配置

```bash
python .claude/skills/feishu-doc-orchestrator/scripts/check_config.py
```

### 3. 使用技能

```
请帮我将 docs/example.md 转换为飞书文档
```

## 支持的25种块类型

**基础文本（11种）**：text, heading1-9, quote_container
**列表（4种）**：bullet, ordered, todo, task
**特殊块（5种）**：code, quote, callout, divider, image
**AI块（1种）**：ai_template
**高级块（5种）**：bitable, grid, sheet, table, board

## 技能架构

```
feishu-doc-orchestrator/        # 主技能
├── feishu-md-parser/               # Markdown解析
├── feishu-doc-creator-with-permission/  # 创建+权限
├── feishu-block-adder/             # 批量添加
├── feishu-doc-verifier/            # 文档验证
└── feishu-logger/                  # 日志记录
```

## 测试脚本

```bash
# 测试所有25种块类型
python .claude/skills/feishu-doc-orchestrator/scripts/test_all_25_blocks.py
```

## 注意事项

⚠️ **重要**：
- 配置文件包含敏感信息，请勿提交到Git
- `.claude/feishu-config.env` 和 `.claude/feishu-token.json` 已在 .gitignore 中
- 发布时请确保不包含个人隐私数据
