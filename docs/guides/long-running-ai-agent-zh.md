# 如何使用 nanobot 运行长期运行的 AI Agent

nanobot 可以通过持续目标、持久 session、计划的自动化、本地触发器以及持续运行的 gateway 进程，让 Agent 工作跨越多个回合保持运行。

## 你将构建的内容

- 一个可运行的本地 Agent
- 一个持久 chat session
- 一个长期运行的目标或自动化
- 一个用于后台交付的 gateway 进程

## 适用场景

当任务不是一次性回答时使用，例如项目工作、定期检查、计划摘要、文件维护、多步骤研究，或来自脚本和构建任务的本地触发器。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

## 最小可运行示例

启动 gateway：

```bash
nanobot gateway
```

在 WebUI 或 chat session 中，启动一个持续目标：

```text
/goal Review this workspace, identify missing tests, and propose the smallest next fix.
```

对于计划运行或基于触发器的运行，请从目标 chat 创建自动化，以便 nanobot 将其关联到正确的 session 和 workspace。

## 生产环境说明

- 对于 chat 应用、WebUI session、自动化和本地触发器，请保持 gateway 运行。
- 对于需要保留上下文的工作，请使用稳定的 session key 或 chat session。
- 让目标范围明确，并清楚说明完成标准。
- 在依赖计划运行之前，请先在 WebUI 中检查 Automations。

## 安全说明

- 将长期运行的目标视为具有实际 tool 访问权限的委派工作。
- 在计划无人值守的任务之前，限制 workspace 和 shell 执行权限。
- 将 chat 访问范围控制在较小范围内，避免未知用户创建目标或自动化。

## 故障排除

- 如果目标似乎卡住，请检查活动 session 和 gateway 日志。
- 如果自动化没有运行，请检查它是否已关联到 chat/session，以及 gateway 是否仍在运行。
- 如果本地触发器失败，请检查从 WebUI Automations 视图复制的命令。

## 相关 nanobot 文档

- [自动化](../automations-zh.md)
- [WebUI 自动化](../webui-zh.md#automations)
- [Chat 命令](../chat-commands-zh.md)
- [Memory](../memory-zh.md)
- [部署](../deployment-zh.md)
