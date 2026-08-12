# nanobot 中 AI Agent Memory 的工作原理

本指南说明如何使用 nanobot 的长期 AI agent memory：session
history、压缩归档、持久 memory 文件、Dream 整合，以及 Git 支持的 memory 变更。

## 你将构建的内容

- 具有持久 session history 的 workspace
- 用于较早轮次的压缩 history 归档
- 如 `USER.md` 和 `MEMORY.md` 之类的持久 memory 文件
- 用于整理长期 memory 的 Dream 工作流

## 何时使用

当 agent 需要跨 session 记住稳定的偏好、项目事实、
决策和重复出现的上下文时，请使用 memory。不要将 memory 用作存放每条原始 transcript 的地方；
nanobot 会将短期消息与经过整理的持久知识分开。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

## 最小可运行示例

在普通 session 中要求 agent 记住一项稳定事实，然后运行 Dream：

```text
/dream
```

检查最近的 memory 变更：

```text
/dream-log
```

具体文件位于活动 workspace 中，通常在
`~/.nanobot/workspace/` 下。

## 生产环境说明

- 每个项目或个人上下文使用一个 workspace。
- 保持持久事实简洁；旧 session 详情应保存在 `history.jsonl` 中。
- 当 workspace 需要自定义 memory 指引时，使用 `/dream-prompt init`。
- 当 memory 会影响重要工作流时，请审查 Git 支持的 memory 变更。

## 安全说明

- Memory 文件可能包含敏感的用户或项目事实。
- 在未审查 `SOUL.md`、`USER.md` 和
  `memory/MEMORY.md` 前，避免共享 workspace。
- 为个人和团队上下文使用独立的 workspace。

## 故障排除

- 如果 memory 感觉过时，请运行 `/dream` 并检查 `/dream-log`。
- 如果 memory 被错误修改，请使用 `/dream-restore` 检查并恢复
  先前版本。
- 如果新的 session 缺少上下文，请确认其使用相同的 workspace。

## 相关 nanobot 文档

- [nanobot 中的 AI Agent Memory](../memory-zh.md)
- [概念](../concepts-zh.md)
- [配置](../configuration-zh.md#auto-compact)
- [Chat Commands](../chat-commands-zh.md)
