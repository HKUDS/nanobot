# Date Arrange - 日程规划模块

基于Nanobot框架的轻量级日程规划模块，提供自然语言任务解析和智能日程安排功能。

## 功能特性

- ✅ 自然语言任务解析
- ✅ 智能日程安排算法
- ✅ 用户偏好记忆存储
- ✅ 简单提醒系统
- ✅ JSON API接口

## 项目结构

```
date_arrange/
├── skills/                 # 技能工具集
│   └── planner/           # 日程规划技能
├── models/                # 数据模型
├── api/                   # API接口
├── utils/                 # 工具函数
└── tests/                 # 测试文件
```

## 快速开始

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行测试
```bash
python -m pytest tests/
```

### 集成到Nanobot

将技能注册到Nanobot的ToolRegistry中：

```python
from date_arrange.skills.planner.task_parser import parse_user_goal
from date_arrange.skills.planner.schedule_creator import create_optimized_schedule

# 注册工具
tool_registry.register_tool(parse_user_goal)
tool_registry.register_tool(create_optimized_schedule)
```

## API文档

### 任务解析接口
```python
POST /conversations/{id}/schedule/parse
{
    "user_input": "需要准备下周的学术报告和代码review"
}
```

### 日程保存接口
```python
POST /conversations/{id}/schedule/save
{
    "schedule": {
        "date": "2024-04-08",
        "tasks": [...]
    }
}
```

## 开发计划

- [x] 项目结构搭建
- [ ] 核心数据模型实现
- [ ] 任务解析工具开发
- [ ] API接口实现
- [ ] 前端集成测试

## 技术栈

- Python 3.8+
- FastAPI (API框架)
- Pydantic (数据验证)
- Nanobot Framework (AI助手框架)