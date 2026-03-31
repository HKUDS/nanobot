---
name: experiment_environment
description: 智能体架构对比实验环境建设技能。用于搭建 Agent 实验框架，包括向量记忆系统集成、多会话 Token 统计、实验流程标准化。
---

# Experiment Environment 技能文档

## 1. 技能名称

**experiment_environment** —— 智能体架构对比实验环境建设

## 2. 适用范围

- 搭建 Agent 系统架构对比实验（记忆机制、工具系统对比）
- 集成向量检索记忆系统（ChromaDB + DeepSeek Embedding）
- 配置多会话 Token 消耗统计（cal_token v3.0 多会话分流版）
- 标准化实验流程，支持 2×2 全因子实验设计

## 3. 核心组件

### 3.1 向量记忆系统

```
nanobot/agent/vector_memory/
├── config.py           # 向量记忆配置
├── embedding_service.py # DeepSeek Embedding API
├── chromadb_store.py   # ChromaDB 存储
├── retrieval.py        # 语义检索
└── hook.py             # 自动注入钩子
```

**配置参数** (`config.py`)：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `enabled` | `True` | 启用/禁用向量记忆 |
| `top_k` | `5` | 检索返回条数 |
| `embedding_dimension` | `768` | 向量维度 |
| `max_memory_tokens` | `4096` | 最大记忆 token 数 |

**开关控制**：

```python
# nanobot/agent/vector_memory/config.py
enabled: bool = True                    # 全部禁用
conversation_enabled: bool = True        # 禁用对话历史
user_profile_enabled: bool = True        # 禁用用户画像
```

### 3.2 多会话 Token 统计

**核心机制**：使用 `ContextVar` 实现异步安全的会话上下文管理。

```python
from nanobot.providers import set_current_session_key, get_current_session_key

# 在实验脚本中
set_current_session_key("VR_CG_Task1_rep1")  # 设置当前会话
# ... 执行 Agent 任务 ...
```

**日志格式**（JSON）：

```json
{"timestamp": "2026-03-29 14:22:17", "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
```

**日志文件位置**：

| 会话状态 | 文件位置 |
|----------|----------|
| 有 session_key | `personal/logs/session_{session_key}_token_usage.txt` |
| 无 session_key | `personal/token_usage.txt` |

**统计方法**：求和法（对每条记录求和）

```python
def calculate_session_total(log_file_path):
    total = 0
    with open(log_file_path) as f:
        for line in f:
            record = json.loads(line.strip())
            total += record["total_tokens"]
    return total
```

### 3.3 集成架构

```
AgentLoop
    │
    ├── set_current_session_key(msg.session_key)  # 入口处设置
    │
    ├── VectorMemoryManager.inject_memory()        # 检索相关记忆
    │
    ├── AgentRunner.run()                          # 执行任务
    │       │
    │       └── OpenAICompatProvider.chat_stream()
    │               │
    │               └── _extract_usage() → _write_usage_to_file()
    │
    └── VectorMemoryManager.store_turn()           # 存储对话
```

## 4. 实验分组设计

### 2×2 全因子实验

| 组号 | 记忆配置 | 工具配置 |
|------|----------|----------|
| 1 | 滑动窗口 (SW) | 粗粒度 (CG) |
| 2 | 滑动窗口 (SW) | 细粒度 (FG) |
| 3 | 向量检索 (VR) | 粗粒度 (CG) |
| 4 | 向量检索 (VR) | 细粒度 (FG) |

### 实验变量

**记忆机制**：
- SW：仅保留最近 8 轮对话
- VR：向量检索 Top-3 + 最近 2 轮完整对话

**工具系统**：
- CG：`execute_python_code(code: str)` 单一工具
- FG：`read_csv`, `calculate_average`, `filter_data` 等专用工具

## 5. 测试任务

| 任务 | 描述 | 评估重点 |
|------|------|----------|
| Task 1 | CSV 数据统计分析（均值、标准差、筛选） | 准确性、Token 消耗、执行时间 |
| Task 2 | 数据清洗与异常值处理 | 鲁棒性、代码生成质量 |
| Task 4 | 长期偏好记忆（15 轮对话） | 记忆召回率、遗忘轮次 |

## 6. 日志目录结构

```
personal/
├── logs/
│   ├── session_VR_CG_Task1_rep1_token_usage.txt
│   ├── session_VR_CG_Task1_rep2_token_usage.txt
│   ├── session_SW_FG_Task2_rep1_token_usage.txt
│   └── ...
├── memory/
│   ├── HISTORY.md
│   └── MEMORY.md
└── token_usage.txt          # 兼容旧格式（无 session_key 时）
```

## 7. 前提条件

- ChromaDB 已安装：`pip install chromadb`
- DeepSeek API 密钥已配置
- 实验数据 CSV 文件已准备
- 任务验证脚本已实现

## 8. 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-03-29 | 初始版本，集成向量记忆 + 多会话 Token 统计 |

## 9. 相关技能

- [cal_token](../cal_token/SKILL.md) —— Token 消耗统计（多会话分流版）
- [memory](../memory/SKILL.md) —— 原生记忆机制
- [vector_memory](../vector_memory/SKILL.md) —— 向量检索记忆（开发中）
