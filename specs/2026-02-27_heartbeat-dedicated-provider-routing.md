# Heartbeat 专用 Provider 路由

## 背景

`gateway.heartbeat.model` 已支持独立模型，但当前实现仅覆盖 model 名称，执行阶段与决策阶段仍复用主会话 provider（api_key/api_base）。
当 heartbeat 模型跨 provider（例如主模型 Anthropic、heartbeat 模型 Gemini）时，可能出现模型与 endpoint 不匹配问题。

## 目标

- Heartbeat 决策与执行都支持专用 provider。
- 保持默认行为兼容：未配置 `gateway.heartbeat.model` 时继续复用主 provider。

## 方案

1. `AgentLoop` 增加 `provider_override` 调用链：
   - `process_direct(..., provider_override=...)`
   - `_process_message(..., provider_override=...)`
   - `_run_agent_loop(..., provider_override=...)`
2. Gateway 启动时计算：
   - `hb_model = gateway.heartbeat.model || agents.defaults.model`
   - `hb_provider = _make_provider(config, model=hb_model)`（仅当 heartbeat.model 配置非空）
3. Heartbeat 两个阶段统一使用 `hb_provider`：
   - 决策阶段：`HeartbeatService(provider=hb_provider, model=hb_model)`
   - 执行阶段：`agent.process_direct(..., model_override=hb_model, provider_override=hb_provider)`

## 验收标准

- 配置 heartbeat 跨 provider 模型时，决策与执行请求都使用 heartbeat 对应 provider 的 key/base。
- 未配置 heartbeat.model 时，行为与当前版本一致（使用主 provider）。
- 新增测试覆盖 `provider_override` 透传与生效。
