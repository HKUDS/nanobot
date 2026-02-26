# Heartbeat 模型与间隔独立配置

## 背景

当前 Heartbeat 机制默认每 30 分钟触发，并沿用 `agents.defaults.model` 执行决策与任务。
当用户希望 Heartbeat 使用更低成本或更快模型时，缺少独立配置入口。

## 目标

- 支持在 `gateway.heartbeat` 下单独配置：
  - `interval_s`：触发间隔（秒）
  - `model`：Heartbeat 专用模型
- Heartbeat 专用模型同时用于：
  - 阶段 1：`HEARTBEAT.md` 任务决策
  - 阶段 2：任务执行（`agent.process_direct`）

## 非目标

- 不改动 cron 调度模型配置。
- 不改动常规对话会话模型选择逻辑。

## 方案

1. 在 `HeartbeatConfig` 增加 `model` 字段（默认空字符串）。
2. 对 `interval_s` 增加最小值校验（`>= 1`）。
3. 在 `nanobot gateway` 启动时计算 `heartbeat_model`：
   - 优先 `gateway.heartbeat.model`
   - 回退 `agents.defaults.model`
4. 为 `AgentLoop.process_direct` 增加 `model_override`，仅对当前调用生效。
5. 文档与模板补充 Heartbeat 配置示例。

## 验收标准

- `config.json` 可设置 `gateway.heartbeat.model` 与 `gateway.heartbeat.intervalS`。
- Heartbeat 执行日志中展示实际间隔，并在配置了专用模型时展示模型信息。
- `process_direct(model_override=...)` 能将模型覆盖传递到 agent 执行入口。
- 新增/更新测试通过（Heartbeat 配置校验与模型覆盖透传）。
