# 开发

本页面汇总了面向贡献者的 nanobot 扩展说明。面向用户的设置和运行时选项位于 [`configuration.md`](configuration-zh.md)。

## 添加 LLM provider

nanobot 使用 `nanobot/providers/registry.py` 中的 provider registry 作为 LLM provider 元数据的权威来源。大多数兼容 OpenAI 的 provider 只需进行两项更改。

1. 向 `PROVIDERS` 添加一个 `ProviderSpec` 条目：

```python
ProviderSpec(
    name="myprovider",
    keywords=("myprovider", "mymodel"),
    env_key="MYPROVIDER_API_KEY",
    display_name="My Provider",
    default_api_base="https://api.myprovider.com/v1",
)
```

2. 在 `nanobot/config/schema.py` 的 `ProvidersConfig` 中添加一个字段：

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = Field(default_factory=ProviderConfig)
```

环境变量、配置匹配、provider 状态和 WebUI 凭据显示均由这两个条目派生。

有用的 `ProviderSpec` 选项：

| 字段 | 描述 |
|---|---|
| `default_api_base` | 默认的兼容 OpenAI 的基础 URL。 |
| `env_extras` | 从 provider 配置派生的其他环境变量。 |
| `model_overrides` | 按模型设置的请求参数覆盖项。 |
| `is_gateway` | provider 可以路由多个模型系列，例如 OpenRouter。 |
| `detect_by_key_prefix` | 根据 API 密钥前缀匹配已配置的 gateway。 |
| `detect_by_base_keyword` | 根据 API 基础 URL 匹配已配置的 gateway。 |
| `strip_model_prefix` | 在将模型发送到上游 API 前移除 `provider/`。 |
| `supports_max_completion_tokens` | 使用 `max_completion_tokens` 代替 `max_tokens`。 |
| `is_transcription_only` | provider 具有凭据，但无法提供聊天补全。 |

## 添加转录 provider

转录有意分为两层：

- `nanobot/audio/transcription_registry.py` 负责 provider 名称、别名、默认模型和适配器加载。
- `nanobot/providers/transcription.py` 负责 provider 特定的 HTTP 行为。

凭据仍位于 `providers.<provider>` 下，因此 chat channels 和 WebUI 会以相同方式解析 API 密钥和 API 基础 URL。

1. 向 `ProvidersConfig` 添加 provider 凭据。

```python
class ProvidersConfig(BaseModel):
    ...
    my_stt: ProviderConfig = Field(default_factory=ProviderConfig)
```

2. 在 `nanobot/providers/registry.py` 中添加一个 `ProviderSpec`。

对于仅支持转录的 provider，设置 `is_transcription_only=True`，使其显示在凭据/设置界面中，但不会出现在 chat 模型选择中。

```python
ProviderSpec(
    name="my_stt",
    keywords=("my_stt",),
    env_key="MY_STT_API_KEY",
    display_name="My STT",
    default_api_base="https://api.example.com/v1",
    is_transcription_only=True,
)
```

3. 在 `nanobot/providers/transcription.py` 中添加一个适配器类。

适配器会接收已解析的凭据和设置。对于 provider 错误，它们返回空字符串，使 channel 语音消息能够静默失败，而不会导致 agent 循环崩溃。

```python
class MySTTTranscriptionProvider:
    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("MY_STT_API_KEY")
        self.api_base = api_base or "https://api.example.com/v1"
        self.language = language or None
        self.model = model or "my-default-stt-model"

    async def transcribe(self, file_path: str | Path) -> str:
        ...
```

4. 在 `nanobot/audio/transcription_registry.py` 中注册适配器。

```python
TranscriptionProviderSpec(
    name="my_stt",
    default_model="my-default-stt-model",
    adapter="nanobot.providers.transcription:MySTTTranscriptionProvider",
    aliases=("mystt",),
)
```

5. 添加测试。

至少覆盖：

- `tests/providers/test_transcription.py` 中的配置解析
- 适配器请求/响应行为以及重试/错误处理
- `tests/webui/test_settings_api.py` 中的 WebUI 设置负载/更新行为
- 如果 provider 出现在 Settings 中，测试 provider 品牌映射

6. 更新面向用户的文档。

在用户选择 `transcription.provider` 的 [`configuration.md`](configuration-zh.md) 中添加该 provider，但将实现细节保留在本开发指南中。
