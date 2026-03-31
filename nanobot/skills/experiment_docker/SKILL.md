---
name: experiment_docker
description: Docker 容器化实验环境建设技能。用于容器隔离执行 Agent 架构对比实验，支持多会话并发和结果自动汇总。
---

# Experiment Docker 技能文档

## 1. 技能名称

**experiment_docker** —— Docker 容器化实验环境

## 2. 适用范围

- 使用 Docker 容器隔离不同实验配置
- 并发执行多组 Agent 架构对比实验
- 自动汇总 Token 消耗和执行结果
- 支持 2×2 全因子实验设计（记忆机制 × 工具系统）

## 3. 目录结构

```
experiment_docker/
├── Dockerfile                  # nanobot 镜像构建
├── docker-compose.yml         # 容器编排
├── __main__.py               # 入口脚本
├── __init__.py
├── orchestrator/
│   ├── __init__.py
│   ├── config.py             # 实验配置数据类
│   ├── runner.py             # 实验调度器
│   └── aggregator.py         # 结果汇总器
├── shared/
│   ├── configs/              # Agent 配置文件
│   │   ├── Agent_VR_CG.json
│   │   ├── Agent_VR_FG.json
│   │   ├── Agent_SW_CG.json
│   │   └── Agent_SW_FG.json
│   └── data/                # 测试数据 CSV
└── results/
    ├── raw/                 # 原始日志
    └── report/              # 汇总报告
```

## 4. 核心组件

### 4.1 ExperimentOrchestrator

```python
from experiment_docker.orchestrator import ExperimentOrchestrator, ExperimentConfig

orchestrator = ExperimentOrchestrator(
    base_dir=Path("experiment_docker"),
    max_concurrent=4,
)

# 构建镜像
orchestrator.build_image()

# 运行单个实验
result = await orchestrator.run_single_experiment(config)

# 批量运行
results = await orchestrator.run_batch(configs, repetitions=10)
```

### 4.2 ResultAggregator

```python
from experiment_docker.orchestrator import ResultAggregator

aggregator = ResultAggregator(results_dir=Path("experiment_docker/results"))
report = aggregator.aggregate_from_results_file(results_file)
```

## 5. 实验配置

| 配置 | 记忆机制 | 工具系统 |
|------|----------|----------|
| VR_CG | 向量检索 (Vector Retrieval) | 粗粒度 (Coarse-Grained) |
| VR_FG | 向量检索 | 细粒度 (Fine-Grained) |
| SW_CG | 滑动窗口 (Sliding Window) | 粗粒度 |
| SW_FG | 滑动窗口 | 细粒度 |

## 6. 使用方法

### 6.1 命令行模式

```bash
# 构建镜像
python -m experiment_docker --build-image

# 单次实验
python -m experiment_docker --mode single --memory-config VR --tool-config CG --task-name Task1

# 批量实验（默认 10 次重复）
python -m experiment_docker --mode batch --repetitions 10

# 汇总结果
python -m experiment_docker --mode aggregate
```

### 6.2 Python API 模式

```python
import asyncio
from pathlib import Path
from experiment_docker.orchestrator import ExperimentOrchestrator, generate_experiment_configs

async def main():
    orchestrator = ExperimentOrchestrator(Path("experiment_docker"))
    configs = generate_experiment_configs()
    results = await orchestrator.run_batch(configs, repetitions=10)
    orchestrator.save_results(results)

asyncio.run(main())
```

## 7. 输出报告格式

```json
{
  "report_date": "2026-03-29T15:30:00",
  "total_experiments": 120,
  "successful": 118,
  "success_rate": 0.983,
  "groups": {
    "VR_CG_Task1": {
      "count": 10,
      "success_rate": 1.0,
      "avg_total_tokens": 12500,
      "min_total_tokens": 11000,
      "max_total_tokens": 14000,
      "std_total_tokens": 850
    }
  }
}
```

## 8. 前提条件

- Docker 已安装并运行
- docker Python SDK：`pip install docker`
- nanobot 项目已就绪

## 9. 相关技能

- [experiment_environment](../experiment_environment/SKILL.md) —— 本地实验环境
- [cal_token](../cal_token/SKILL.md) —— Token 消耗统计
