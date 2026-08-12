# 如何在 nanobot 中配置 model fallback

model fallback 允许 nanobot 先尝试 primary model，然后在 primary provider 失败或受到速率限制时，切换到一个或多个已命名的 preset。

## 你将构建的内容

- 两个或更多 `modelPresets`
- 一个 primary `agents.defaults.modelPreset`
- 一个有序的 `agents.defaults.fallbackModels` 链

## 何时使用此功能

当你希望在速率限制、provider 中断、本地 model 停机或对成本敏感的路由场景下获得更好的可靠性时，可以使用 fallback。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

在将每个 provider 添加为 fallback 之前，请先确认其运行正常。

## 最小可用示例

将此结构合并到 `~/.nanobot/config.json` 中，并将 provider/model 名称替换为你控制的名称：

```json
{
  "modelPresets": {
    "fast": {
      "label": "Fast",
      "provider": "primary-provider",
      "model": "primary-model-id",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "deep": {
      "label": "Deep",
      "provider": "fallback-provider",
      "model": "fallback-model-id",
      "maxTokens": 4096,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast",
      "fallbackModels": ["deep"]
    }
  }
}
```

`fallbackModels` 中的字符串条目是 preset 名称，而不是原始 model ID。
请将占位 model ID 替换为 provider 当前支持的 model ID。[Provider Cookbook](../provider-cookbook-zh.md) 中提供了常见 provider 的具体配置方案。

## 生产环境注意事项

- 保持 fallback context window 大小合理；较小的 fallback window 会限制可容纳的 context 大小。
- 在可接受的情况下，将成本更低或速度更快的 fallback 放在成本更高的 fallback 之前。
- 使用 `/model <preset>` 在运行时切换，无需编辑配置。
- 对 WebUI model 列表使用易于理解的标签。

## 安全注意事项

- 不同 provider 可能具有不同的数据处理政策。
- 不要将 provider key 直接放入共享配置文件中。
- 确认 fallback model 可以安全地接收相同的 prompts 和文件。

## 故障排除

- 如果 fallback 从未触发，请确认 primary error 被视为可重试或可触发 fallback 的错误。
- 如果启动失败，请检查每个 fallback 字符串是否与 `modelPresets` 下的某个 key 匹配。
- 如果切换到 fallback 后输出被截断，请检查 `maxTokens` 和 `contextWindowTokens`。

## 相关 nanobot 文档

- [Providers and Models](../providers-zh.md)
- [Provider Cookbook: Fallback Presets](../provider-cookbook-zh.md#recipe-fallback-presets)
- [Configuration: Model Fallbacks](../configuration-zh.md#model-fallbacks)
