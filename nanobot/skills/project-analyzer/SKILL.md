---
name: project-analyzer
description: Analyze local Python projects using the project_analyzer tool.
---

# Project Analyzer Skill

## 功能说明

此 skill 用于指导 Agent 何时以及如何使用 `project_analyzer` 工具分析用户指定的本地 Python 项目。

## 何时使用

当用户要求执行以下任一操作时，使用 `project_analyzer` 工具：

- "分析这个项目"
- "帮我了解这个代码库"
- "这个项目是做什么的？"
- "这个项目怎么运行？"
- "分析目录 /path/to/project"
- "帮我看看这个项目的结构"

## 使用方式

### 1. 要求用户提供明确的项目路径

在调用 `project_analyzer` 之前，必须确认用户提供了**明确的项目目录路径**。

例如，当用户说：
- "帮我分析一下这个项目" → 询问："请问您的项目目录路径是什么？"
- "分析 myproject" → 先确认完整路径，或要求用户提供绝对路径

### 2. 调用 project_analyzer 工具

确认路径后，调用 `project_analyzer` 工具：

```
project_analyzer(path="/absolute/path/to/your/project")
```

### 3. 分析输出结果

工具将返回一个 Markdown 格式的报告，包含以下部分：

1. **项目简介** - 项目名称、版本、描述、路径
2. **目录结构** - 项目目录树摘要
3. **运行方式** - 如何安装和运行项目
4. **核心模块** - 主要 Python 文件分析
5. **依赖分析** - 项目依赖列表
6. **可优化点** - 潜在的改进建议
7. **潜在风险** - 需要注意的问题

### 4. 给用户的回复

根据分析结果，向用户提供：
- 项目的整体概述
- 关键文件和模块的说明
- 如何运行项目的指导
- 任何值得注意的优化点或风险

## 重要提示

### 路径安全
- `project_analyzer` 只能分析用户显式指定的目录
- 禁止访问系统敏感目录（如 `/`、`C:\`、`/etc`、`C:\Windows` 等）
- 禁止访问用户主目录本身

### 性能考虑
- 工具会自动设置合理的扫描上限（最大文件数、最大读取字节数、最大目录深度）
- 对于大型项目，分析结果会自动截断关键信息

### 工具特性
- 此工具是**只读**的，不会修改任何文件
- 工具会解析：
  - `README.md` / `README.rst` / `README.txt`
  - `pyproject.toml`（使用标准库 `tomllib` 或兼容解析）
  - `requirements.txt`
  - 主要 Python 文件（根目录 `.py` 文件、包目录 `__init__.py` 等）

## 示例对话

**用户**: "帮我分析一下 ~/workspace/myproject 这个项目"

**Agent**: 调用 `project_analyzer(path="/home/user/workspace/myproject")`

**工具返回**: [完整的项目分析报告]

**Agent**: [基于报告向用户解释项目结构、如何运行、主要模块等]
