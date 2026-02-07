# 自动记忆系统升级指南

## 概述

nanobot 现在包含一个智能自动记忆系统，可以自动总结对话并更新长期记忆。本指南帮助您从手动记忆管理升级到自动系统。

## 新功能

### 自动总结
- 每隔 N 条用户消息（默认 10 条）自动触发
- 提取话题、偏好、决定、任务和技术问题
- 生成结构化的每日概要 Markdown 文件

### 智能去重
- 相似内容不会被重复记录
- 基于字符串相似度判断（阈值 80%）

### 重要性评分
- 自动评估信息的重要性（1-3 分）
- 只有重要信息（≥2 分）才会被记录到长期记忆

### 灵活配置
- 支持配置文件和环境变量
- 可以为总结使用独立的模型（降低成本）
- 可以完全禁用自动记忆功能

## 配置

### 方式 1：配置文件

编辑 `~/.nanobot/config.json`:

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    },
    "summary": {
      "enabled": true,
      "model": "deepseek/deepseek-chat",
      "interval": 10,
      "maxTokens": 4000
    }
  }
}
```

### 方式 2：环境变量

```bash
# 禁用自动记忆
export NANOBOT_AUTO_SUMMARY=false

# 使用特定模型进行总结
export NANOBOT_SUMMARY_MODEL="deepseek/deepseek-chat"

# 更改触发间隔
export NANOBOT_SUMMARY_INTERVAL=5
```

## 文件位置

自动记忆系统会创建以下文件：

```
~/.nanobot/workspace/
└── memory/
    ├── 2026-02-07.md      # 每日对话概要
    ├── 2026-02-08.md      # 每日对话概要
    ├── .template.md        # 模板文件
    └── MEMORY.md          # 长期记忆汇总
```

## 使用方法

### 自动模式（推荐）

默认启用，无需任何操作。系统会自动：

1. 追踪用户消息数量
2. 达到阈值时生成总结
3. 更新长期记忆
4. 不影响主对话流程（异步执行）

### 手动模式

如果您需要完全控制，可以禁用自动记忆：

```bash
export NANOBOT_AUTO_SUMMARY=false
```

然后手动读取和写入记忆文件：

```python
from pathlib import Path

memory_file = Path.home() / ".nanobot" / "workspace" / "memory" / "MEMORY.md"
memory_file.write_text("重要信息...", encoding="utf-8")
```

## 成本优化

使用更便宜的模型进行总结，可以显著降低成本：

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    },
    "summary": {
      "model": "deepseek/deepseek-chat"
    }
  }
}
```

**成本对比**（基于 2026 年 2 月价格）：
- Claude Opus 4-5: ~$15/M tokens
- DeepSeek Chat: ~$1/M tokens
- **节省约 85% 总结成本**

## 回滚到手动模式

如果自动记忆不符合您的需求，可以轻松回滚：

### 1. 禁用自动记忆

```bash
export NANOBOT_AUTO_SUMMARY=false
```

或在配置文件中设置：

```json
{
  "agents": {
    "summary": {
      "enabled": false
    }
  }
}
```

### 2. 手动管理记忆

您仍然可以手动读取和写入记忆文件，就像之前一样：

```python
from pathlib import Path

# 读取长期记忆
memory_file = Path.home() / ".nanobot" / "workspace" / "memory" / "MEMORY.md"
content = memory_file.read_text(encoding="utf-8")

# 更新记忆
new_content = content + "\n\n" + "新信息"
memory_file.write_text(new_content, encoding="utf-8")
```

## 常见问题

### Q: 自动记忆会使用多少 API token？

A: 取决于对话长度和配置。默认情况下：
- 总结模型使用 ~1000-4000 tokens
- 每 10 条用户消息触发一次

### Q: 如何检查自动记忆是否正常工作？

A: 检查日志输出和文件生成：

```bash
# 查看日志
nanobot agent

# 检查文件
ls -la ~/.nanobot/workspace/memory/
```

### Q: 自动记忆会影响对话速度吗？

A: 不会。总结任务在后台异步执行，不会阻塞主对话流程。

### Q: 如何清理旧的每日概要？

A: 手动删除不需要的文件：

```bash
rm ~/.nanobot/workspace/memory/2026-01-*.md
```

### Q: 可以自定义总结格式吗？

A: 可以。编辑 `ConversationSummarizer._format_daily_summary()` 方法自定义格式。

## 迁移检查清单

- [ ] 更新配置文件（如果需要）
- [ ] 设置环境变量（如果需要）
- [ ] 测试自动记忆功能（发送 10 条以上消息）
- [ ] 检查生成的每日概要文件
- [ ] 验证长期记忆正确更新
- [ ] 根据需要调整配置参数

## 需要帮助？

如果遇到问题，请：
1. 检查日志输出
2. 验证配置文件格式
3. 查看 [GitHub Issues](https://github.com/HKUDS/nanobot/issues)

---

*最后更新：2026-02-07*
