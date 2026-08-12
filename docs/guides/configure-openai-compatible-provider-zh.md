# 如何在 nanobot 中配置 OpenAI 兼容 provider

nanobot 可以通过配置 `apiBase`、可选的 `apiKey`，以及引用该 provider 名称的模型预设来调用 OpenAI 兼容的模型 provider。

## 你将构建的内容

- 一个自定义 provider 条目
- 一个指向该 provider 的模型预设
- 一次成功的 `nanobot agent` 运行

## 适用场景

当本地或托管服务提供 OpenAI 兼容的端点时使用此配置，包括内部 gateway、本地模型服务器，以及 nanobot 中尚未命名的 provider 代理。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

在调试 nanobot 之前，先确认端点能够响应：

```bash
curl -sS https://api.example.com/v1/models
```

## 最小可运行示例

将以下内容合并到 `~/.nanobot/config.json`：

```json
{
  "providers": {
    "custom": {
      "apiKey": "${CUSTOM_API_KEY}",
      "apiBase": "https://api.example.com/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Custom",
      "provider": "custom",
      "model": "provider-model-name",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

然后运行：

```bash
nanobot agent -m "Hello!"
```

## 生产环境注意事项

- 当服务要求使用 `/v1` 时，在 `apiBase` 中包含版本路径。
- 为不同端点使用不同的 provider 名称。
- 仅当端点要求非空密钥但不会验证密钥时，才使用诸如 `EMPTY` 的占位密钥。
- 对于自定义 OpenAI 兼容端点，不要设置 `apiType`。

## 安全注意事项

- 将 provider 密钥保存在环境变量中。
- 将内部模型 gateway 视为敏感网络服务。
- 对于私有 workspace，不要将 nanobot 指向不受信任的代理端点。

## 故障排除

- 如果 `curl /models` 失败，请先修复 provider 端点，再更改 nanobot。
- 如果 nanobot 提示模型未知，请检查 provider 所需的模型 ID。
- 如果身份验证失败，请确认 provider 是否要求 Bearer 身份验证，以及启动 nanobot 的环境中是否存在该密钥。

## 相关 nanobot 文档

- [Provider 手册：自定义 OpenAI 兼容 provider](../provider-cookbook-zh.md#recipe-custom-openai-compatible-provider)
- [Providers：自定义 OpenAI 兼容端点](../providers-zh.md#custom-openai-compatible-endpoint)
- [OpenAI 兼容 Agent API](openai-compatible-agent-api-zh.md)
