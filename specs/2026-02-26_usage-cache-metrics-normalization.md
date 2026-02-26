# Usage Cache Metrics Normalization

## 背景

`agent.loop` 的 token 日志仅在 `usage` 包含 `cache_creation_input_tokens` 或 `cache_read_input_tokens` 时打印 cache 命中信息。  
当前 provider 层仅上报 `prompt/completion/total`，导致日志经常显示 `cache: n/a`，无法反映真实缓存命中。

## 目标

- 统一 `LiteLLMProvider` 的 `usage` 解析逻辑，兼容 OpenAI 与 Anthropic 的缓存字段。
- 在不破坏现有 token 统计的前提下，为日志层补齐 cache 指标。

## 方案

- 在 `LiteLLMProvider` 新增 usage 归一化方法：
  - 优先读取标准字段：`prompt_tokens`、`completion_tokens`、`total_tokens`
  - 兼容 Anthropic 字段：`input_tokens`、`output_tokens`、`cache_creation_input_tokens`、`cache_read_input_tokens`
  - 兼容 OpenAI 字段：`prompt_tokens_details.cached_tokens`（映射到 `cache_read_input_tokens`）
- 将流式与非流式解析统一改为调用该归一化方法。

## 验收标准

- OpenAI 返回 `prompt_tokens_details.cached_tokens` 时，日志不再出现 `cache: n/a`。
- Anthropic 返回 `cache_creation_input_tokens/cache_read_input_tokens` 时，日志可打印 `create/read/hit_rate`。
- 现有 `prompt/completion/total` 输出保持不变。
