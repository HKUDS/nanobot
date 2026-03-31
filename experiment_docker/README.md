# Experiment Docker 使用指南

## 📋 概述

本实验框架使用 Docker 容器隔离技术，为每个实验创建独立的运行环境，确保实验之间的上下文完全隔离。

## 🎯 核心特性

### 1. 完全隔离

每个实验运行在独立的 Docker 容器中，拥有：
- ✅ 独立的 workspace 目录
- ✅ 独立的 memory（MEMORY.md 和 HISTORY.md）
- ✅ 独立的 session 历史
- ✅ 独立的配置文件

### 2. 上下文隔离机制

```
实验 1 → Container 1 → /root/.nanobot/workspaces/exp_001/
                          ├── memory/
                          │   ├── MEMORY.md (只有实验 1 的数据)
                          │   └── HISTORY.md (只有实验 1 的数据)
                          ├── skills/
                          └── config.json

实验 2 → Container 2 → /root/.nanobot/workspaces/exp_002/
                          ├── memory/
                          │   ├── MEMORY.md (只有实验 2 的数据)
                          │   └── HISTORY.md (只有实验 2 的数据)
                          ├── skills/
                          └── config.json
```

### 3. 环境变量注入

每个容器启动时注入以下环境变量：
```bash
SESSION_KEY=VR_CG_Task1_rep1          # 会话标识
MEMORY_CONFIG=VR                       # 记忆配置
TOOL_CONFIG=CG                         # 工具配置
TASK_NAME=Task1                        # 任务名称
NANOBOT_MODEL=deepseek-chat           # 模型
NANOBOT_WORKSPACE=/root/.nanobot/workspaces/VR_CG_Task1_rep1  # 独立工作空间
RESULT_DIR=/app/results/raw/VR_CG_Task1_rep1  # 结果目录
```

---

## 🚀 快速开始

### 1. 构建 Docker 镜像

```bash
# 首次使用需要构建镜像
python -m experiment_docker --build-image
```

### 2. 运行单个实验

```bash
# 运行单个实验（VR 记忆 + CG 工具）
python -m experiment_docker \
    --mode cli \
    --memory-config VR \
    --tool-config CG \
    --task-name Task1 \
    --timeout 300
```

### 3. 批量运行实验

```bash
# 批量运行所有配置（10 次重复）
python -m experiment_docker \
    --mode cli \
    --batch \
    --repetitions 10 \
    --batch-size 4 \
    --batch-delay 2.0 \
    --timeout 1800
```

**参数说明**：
- `--batch-size 4`: 同时运行 4 个容器（根据 CPU/内存调整）
- `--batch-delay 2.0`: 批次间延迟 2 秒（避免 API 限流）
- `--timeout 1800`: 每个实验超时 30 分钟

---

## 📊 运行模式

### 模式对比

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `local` | 本地直接运行 | 快速测试、调试 |
| `cli` | Docker 命令行 | **推荐**，生产环境 |
| `docker-sdk` | Docker Python SDK | 需要精细控制 |
| `aggregate` | 汇总结果 | 生成报告 |
| `clean` | 清理容器 | 释放资源 |
| `status` | 查看状态 | 监控进度 |

---

## 🔧 常用命令

### 查看实验状态

```bash
python -m experiment_docker --mode status
```

输出示例：
```
================================================================================
Docker 容器状态
================================================================================

运行中的容器:
NAMES                    STATUS          RUNNING FOR
nanobot_exp_VR_CG_1      Up 2 minutes    2 minutes ago

工作空间数量：15
最近的工作空间:
  - VR_CG_Task1_rep1 (创建时间：2026-03-30T10:30:00)
  - VR_FG_Task1_rep1 (创建时间：2026-03-30T10:28:00)

结果文件数量：10
最近的结果:
  - results_20260330_103000.json (修改时间：2026-03-30T10:35:00)
================================================================================
```

---

### 清理容器

```bash
# 清理所有实验容器（保留工作空间）
python -m experiment_docker --mode clean

# 清理容器和工作空间（彻底清理）
python -m experiment_docker --mode clean --all
```

---

### 汇总结果

```bash
# 从原始日志生成报告
python -m experiment_docker --mode aggregate

# 报告位置：experiment_docker/results/report/
```

---

## 📁 目录结构

```
experiment_docker/
├── orchestrator/           # 调度器
│   ├── runner.py          # 实验运行器
│   ├── config.py          # 配置定义
│   ├── batch_executor.py  # 分批执行
│   └── aggregator.py      # 结果汇总
│
├── workspaces/            # 工作空间（每个实验独立）
│   ├── VR_CG_Task1_rep1/
│   │   ├── memory/
│   │   │   ├── MEMORY.md
│   │   │   └── HISTORY.md
│   │   ├── skills/
│   │   └── config.json
│   └── VR_FG_Task1_rep1/
│
├── results/               # 实验结果
│   ├── raw/              # 原始结果
│   │   ├── VR_CG_Task1_rep1/
│   │   │   ├── experiment.log
│   │   │   └── token_usage.txt
│   │   └── results_*.json
│   └── report/           # 汇总报告
│
├── shared/               # 共享资源
│   ├── configs/          # 配置文件模板
│   └── data/             # 任务数据
│
├── Dockerfile            # Docker 镜像定义
└── __main__.py          # 入口脚本
```

---

## 🎯 Token 统计

### Token 记录方式

每个实验的 token 使用记录在两个位置：

1. **容器内**：`/root/.nanobot/workspaces/{session_key}/personal/token_usage.txt`
2. **宿主机**：`experiment_docker/results/raw/{session_key}/token_usage.txt`

### Token 文件格式

```json
{"prompt_tokens": 1500, "completion_tokens": 500, "total_tokens": 2000, "session_key": "VR_CG_Task1_rep1"}
{"prompt_tokens": 1600, "completion_tokens": 550, "total_tokens": 2150, "session_key": "VR_CG_Task1_rep1"}
```

### 读取 Token 统计

Runner 会自动从以下文件读取：
- `*token_usage*.txt`
- `*token_usage*.json`

如果不存在，则从日志中解析。

---

## 🔍 故障排除

### 问题 1：Docker 不可用

```bash
# 检查 Docker 是否运行
docker info

# 如果失败，启动 Docker Desktop
```

### 问题 2：容器启动失败

```bash
# 查看详细日志
docker logs nanobot_exp_VR_CG_Task1_rep1

# 或者使用 status 模式
python -m experiment_docker --mode status
```

### 问题 3：Token 统计为 0

**原因**：token_usage 文件未生成或未挂载

**解决方案**：
1. 检查卷挂载是否正确
2. 检查 `NANOBOT_WORKSPACE` 环境变量
3. 查看容器日志确认 token 记录

```bash
# 手动查看容器内的文件
docker exec -it nanobot_exp_VR_CG_Task1_rep1 \
    cat /root/.nanobot/workspaces/VR_CG_Task1_rep1/personal/token_usage.txt
```

### 问题 4：内存不足

```bash
# 减少并发数量
python -m experiment_docker \
    --batch-size 2 \  # 从 4 减少到 2
    --max-concurrent 2
```

---

## 📊 实验配置

### 生成实验配置

```python
from experiment_docker.orchestrator.config import generate_experiment_configs

configs = generate_experiment_configs()
# 生成 4 种基础配置：
# - VR_CG, VR_FG, SW_CG, SW_FG
```

### 自定义配置

```python
from experiment_docker.orchestrator.config import ExperimentConfig

config = ExperimentConfig(
    session_key="custom_exp_1",
    memory_config="VR",      # VR 或 SW
    tool_config="CG",        # CG 或 FG
    task_name="Task1",
    model="deepseek-chat",   # 或 qwen-max, kimi
    repetition=1,
)
```

---

## 🎯 最佳实践

### 1. 批量执行

```bash
# 推荐：分批执行，避免超时
python -m experiment_docker \
    --mode cli \
    --batch \
    --repetitions 10 \
    --batch-size 4 \
    --batch-delay 2.0 \
    --timeout 1800
```

### 2. 资源管理

```bash
# 根据系统资源调整并发
# 8GB 内存：--batch-size 2
# 16GB 内存：--batch-size 4
# 32GB 内存：--batch-size 8
```

### 3. 结果备份

```bash
# 定期备份结果目录
cp -r experiment_docker/results experiment_docker/results_backup_$(date +%Y%m%d)
```

### 4. 定期清理

```bash
# 每天实验结束后清理
python -m experiment_docker --mode clean --all
```

---

## 📈 性能优化

### 1. 镜像预构建

```bash
# 提前构建镜像，避免每次运行都构建
python -m experiment_docker --build-image
```

### 2. 使用本地缓存

```bash
# Docker 会自动缓存层，首次构建后后续很快
docker images | grep nanobot
```

### 3. 并行执行

```bash
# 增加并发（如果资源允许）
python -m experiment_docker \
    --batch-size 8 \
    --max-concurrent 8
```

---

## 🔗 相关文件

- `runner.py` - 实验运行器
- `config.py` - 配置定义
- `batch_executor.py` - 分批执行逻辑
- `aggregator.py` - 结果汇总
- `Dockerfile` - Docker 镜像定义
- `__main__.py` - 入口脚本

---

**创建时间**: 2026-03-30  
**版本**: 1.0  
**状态**: ✅ 已实施并验证
