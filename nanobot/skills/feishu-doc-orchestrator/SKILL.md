---
name: feishu-doc-orchestrator
description: 飞书文档创建主编排技能 - 将 Markdown 文件转换为飞书文档，编排多个子技能协作完成，支持25种飞书文档块类型。
---

# 飞书文档创建技能 - GitHub发布版

将 Markdown 文件转换为飞书文档，支持25种块类型，完整权限管理。

## 快速开始

### 1. 配置飞书应用

所有配置通过环境变量读取：

```bash
# 必需
NANOBOT_CHANNELS__FEISHU__APP_ID=cli_xxx
NANOBOT_CHANNELS__FEISHU__APP_SECRET=xxxxxxxx

# 可选
FEISHU_AUTO_COLLABORATOR_ID=ou_xxx
FEISHU_DEFAULT_FOLDER=folder_token
FEISHU_API_DOMAIN=https://open.feishu.cn  # 默认值
```

### 2. 使用技能

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
feishu-doc-orchestrator/             # 主技能
└── feishu-doc-orchestrator/         # 编排脚本
feishu-shared/                       # 共享子技能（与 wiki-orchestrator 共用）
├── feishu-md-parser/                # Markdown解析
├── feishu-doc-creator-with-permission/  # 创建+权限
├── feishu-block-adder/              # 批量添加
├── feishu-doc-verifier/             # 文档验证
└── feishu-logger/                   # 日志记录
```

## 测试脚本

```bash
# 测试所有25种块类型
python3 scripts/test_all_25_blocks.py
```

## 注意事项

- 飞书凭据通过环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `APP_SECRET` 注入，不使用配置文件
- 发布时请确保不包含个人隐私数据
