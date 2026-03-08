---
name: feishu-message-recall
description: 飞书消息撤回/删除工具 - 用于撤回或删除已发送的消息。...
---

# Feishu Message Recall Skill

飞书消息撤回/删除工具 - 用于撤回或删除已发送的消息。

## 功能

- 删除普通群消息
- 删除话题（Thread）中的消息
- 批量删除消息
- 查询消息历史

## 使用方式

### 1. 删除单条消息

```python
from skills.feishu_message_recall.scripts.recall import delete_message

# 删除消息
result = delete_message("om_x100b5741b264fca0c12f636d26d1cdd")
print(result)
```

### 2. 批量删除话题中的消息

```python
from skills.feishu_message_recall.scripts.recall import delete_thread_messages

# 删除话题中我发送的所有消息
results = delete_thread_messages("omt_1ae2d7a2164f9ce5")
print(f"删除成功: {results['success']}, 失败: {results['failed']}")
```

### 3. 命令行使用

```bash
# 删除单条消息
python3 skills/feishu-message-recall/scripts/recall.py --msg-id om_x100b5741b264fca0c12f636d26d1cdd

# 删除话题中的所有消息
python3 skills/feishu-message-recall/scripts/recall.py --thread-id omt_1ae2d7a2164f9ce5

# 查询话题中的消息
python3 skills/feishu-message-recall/scripts/recall.py --list-thread omt_1ae2d7a2164f9ce5
```

## API 限制

- 只能删除**自己发送的消息**
- 超过 24 小时的消息可能无法删除
- 话题消息的删除权限与普通群消息相同

## 配置

技能使用以下配置：
- `APP_ID`: 飞书应用 ID
- `APP_SECRET`: 飞书应用 Secret

配置从环境变量或 `config.py` 文件读取。

## 依赖

- Python 3.8+
- requests

## 更新记录

- 2026-02-08: 初始版本，支持消息删除和话题消息批量删除
