# Memory Consolidation 独立模型配置

## 背景

当前记忆归档（`MEMORY.md` / `HISTORY.md`）总结流程固定使用 `agents.defaults.model`。  
当主对话模型较贵或响应较慢时，用户无法为总结任务单独指定一个更便宜/更快的模型。

## 目标

- 新增可选配置 `agents.defaults.memory_consolidation_model`。
- `_consolidate_memory()` 执行时优先使用该模型。
- 未配置时保持兼容：继续使用主模型 `agents.defaults.model`。

## 非目标

- 本次不恢复自动 consolidation 调度（`_should_schedule_consolidation` 仍为 disabled）。
- 本次不引入独立 provider 实例或独立 API key 配置。

## 方案

1. 在 `AgentDefaults` 中新增字符串字段：
   - `memory_consolidation_model`（默认空字符串）
2. 在 CLI / Gateway / Cron 构造 `AgentLoop` 时透传该字段。
3. 若配置了该模型，按该模型重新匹配 provider（api_key/api_base），避免沿用主会话 provider。
4. 在 `AgentLoop._consolidate_memory()` 计算：
   - `consolidation_model = self.memory_consolidation_model or self.model`
5. 调用 consolidation provider 的 `chat(...)` 并使用 `consolidation_model`。
6. 对 Gemini 模型名做兼容归一化：
   - `gemini/models/<name>` → `gemini/<name>`
   - `models/<name>`（且识别为 Gemini）→ `gemini/<name>`
7. `nanobot status` 在该字段已配置时显示当前 consolidation 模型。

## 验收标准

- 配置了 `agents.defaults.memory_consolidation_model` 时，consolidation 请求使用该模型。
- 配置了 `agents.defaults.memory_consolidation_model` 且与主模型 provider 不同（如 Anthropic → Gemini）时，仍可正确路由到对应 provider。
- `gemini/models/...` 形式的配置不会因模型名格式问题导致空模型错误。
- 未配置时，consolidation 请求仍使用主模型。
- 相关单测覆盖上述两条行为并通过。
