# providers/ 模块逻辑总结

## 文件结构

```
providers/
├── __init__.py           # 导出 LLMProvider, LLMResponse, LiteLLMProvider
├── base.py               # 抽象基类 + 数据结构定义
├── registry.py           # Provider 注册表（元数据中心）
├── litellm_provider.py   # LiteLLM 实现（唯一的 chat 实现）
└── transcription.py      # 语音转文字（Groq Whisper，独立于 chat 体系）
```

## 核心调用链

```
config.json 配置
    ↓
_make_provider() (cli/commands.py)
    ↓ 读取 config，调用 config.get_provider() 匹配 provider
    ↓ 传入 api_key, api_base, model, extra_headers, provider_name
    ↓
LiteLLMProvider.__init__()
    ↓ find_gateway() → 检测是否为网关/本地部署
    ↓ _setup_env()   → 设置环境变量（OPENAI_API_KEY 等）
    ↓
LiteLLMProvider.chat()
    ↓ _resolve_model()        → 解析模型名（加前缀）
    ↓ _apply_model_overrides() → 应用模型特定参数
    ↓ 构建 kwargs（model, api_base, api_key, extra_headers, tools）
    ↓
litellm.acompletion(**kwargs)  → 发送 HTTP 请求
    ↓
_parse_response() → 统一解析为 LLMResponse
```

## 各文件职责

### base.py — 抽象接口

定义三个核心类型：

- **`ToolCallRequest`**: LLM 返回的工具调用请求（id, name, arguments）
- **`LLMResponse`**: 统一响应格式（content, tool_calls, finish_reason, usage, reasoning_content）
- **`LLMProvider`**: 抽象基类，要求实现 `chat()` 和 `get_default_model()`

### registry.py — Provider 注册表

**设计理念**：所有 provider 元数据集中管理，避免 if-elif 链。新增 provider 只需两步：
1. 在 `PROVIDERS` 元组中添加 `ProviderSpec`
2. 在 `config/schema.py` 的 `ProvidersConfig` 中加字段

**`ProviderSpec` 关键字段**：

| 字段 | 作用 | 示例 |
|------|------|------|
| `name` | 配置字段名 | `"deepseek"` |
| `keywords` | 模型名匹配关键字 | `("deepseek",)` |
| `env_key` | LiteLLM 需要的环境变量名 | `"DEEPSEEK_API_KEY"` |
| `litellm_prefix` | 模型名前缀（LiteLLM 路由用） | `"deepseek"` → `deepseek/deepseek-chat` |
| `is_gateway` | 是否为网关（可转发任意模型） | OpenRouter, AiHubMix |
| `is_local` | 是否为本地部署 | vLLM |
| `strip_model_prefix` | 网关模式下是否去掉原前缀再重加 | AiHubMix: `anthropic/claude` → `openai/claude` |
| `model_overrides` | 特定模型的参数覆盖 | kimi-k2.5 强制 temperature=1.0 |

**PROVIDERS 注册顺序（= 匹配优先级）**：

1. **网关**：OpenRouter (`sk-or-` 前缀检测), AiHubMix (`aihubmix` URL 检测)
2. **标准 API**：Anthropic, OpenAI, DeepSeek, Gemini, Zhipu, DashScope, Moonshot
3. **本地部署**：vLLM
4. **辅助**：Groq

**三个查找函数**：

- `find_by_model(model)` → 按模型名关键字匹配标准 provider（跳过网关/本地）
- `find_gateway(provider_name, api_key, api_base)` → 检测网关/本地：优先按 config key 名，其次按 api_key 前缀，最后按 api_base URL 关键字
- `find_by_name(name)` → 按名称精确查找

### litellm_provider.py — LiteLLM 实现

唯一的 `LLMProvider` 实现，通过 LiteLLM 库统一对接所有 provider。

**初始化流程**：

1. `find_gateway()` 检测是否为网关/本地模式
2. `_setup_env()` 设置 LiteLLM 所需的环境变量（如 `OPENAI_API_KEY`）
   - 网关模式：强制覆盖 env（`os.environ[key] = val`）
   - 标准模式：仅设默认值（`os.environ.setdefault(key, val)`）

**模型名解析 `_resolve_model()`**：

- 网关模式：去掉原前缀（如果 `strip_model_prefix=True`），加网关前缀
  - 例：AiHubMix 下 `anthropic/claude-3` → `openai/claude-3`
- 标准模式：按 registry 的 `litellm_prefix` 加前缀
  - 例：`deepseek-chat` → `deepseek/deepseek-chat`
  - 已有正确前缀的（在 `skip_prefixes` 中）不重复加

**请求发送 `chat()`**：

- 显式传递 `api_key` 和 `api_base`（避免环境变量干扰）
- 支持 `extra_headers`（用于 AiHubMix APP-Code 等）
- 错误时返回 `LLMResponse(content="Error...", finish_reason="error")` 而非抛异常

### transcription.py — 语音转文字

独立于 chat 体系的 `GroqTranscriptionProvider`，使用 Groq 的 Whisper API 做音频转文字。通过 httpx 直接调用，不走 LiteLLM。

## Provider 匹配逻辑（config/schema.py 中）

`Config._match_provider(model)` 决定用哪个 provider 配置：

1. 遍历 PROVIDERS 注册表，找模型名中包含 keyword 且配了 api_key 的
2. 兜底：取第一个有 api_key 的 provider（网关优先）

**注意**：目前不支持显式指定 provider，完全靠模型名关键字推断。
