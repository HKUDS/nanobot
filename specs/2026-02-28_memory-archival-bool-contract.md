# Memory Archival False Failure Fix — 2026-02-28

## 背景

在合并 upstream 后，`/new` 命令采用“归档成功才清 session”的同步模式。

## 问题现象

- consolidation 日志显示成功（`Memory consolidation done`）
- 但用户收到：`Memory archival failed, session not cleared. Please try again.`

## 根因

`/new` 分支将 `_consolidate_memory()` 作为布尔结果判断：

- 调用侧：`if not await self._consolidate_memory(...):` 失败则直接报错并不清会话
- 实现侧：`_consolidate_memory()` 签名为 `-> None`，成功路径没有 `return True`

导致成功执行后返回 `None`，被 `if not ...` 当成失败。

## 方案

统一 `_consolidate_memory()` 的返回契约为 `bool`：

- 成功执行返回 `True`
- 无需 consolidation 的早退路径返回 `True`
- LLM 空响应/结构异常/异常捕获返回 `False`

并补充回归测试：`/new` 走真实 `_consolidate_memory()` 路径时，不应误报失败。

## 验收

- `/new` 在归档成功时返回 `New session started...` 并清空会话
- 归档失败时仍返回失败文案并保留会话
- 相关测试通过
