# 自定义Provider功能说明

## 快速开始

SkyLeap-nanobot现在支持通过配置文件添加自定义LLM provider，无需修改代码即可使用任何OpenAI兼容的API。

## 配置示例

### NVIDIA API配置

```json
{
  "providers": {
    "customProviders": [
      {
        "name": "nvidia",
        "displayName": "NVIDIA API",
        "apiKey": "nvapi-xxxxxxxxxxxx",
        "apiBase": "https://integrate.api.nvidia.com/v1",
        "models": [
          "z-ai/glm4.7",
          "moonshotai/kimi-k2.5",
          "minimaxai/minimax-m2.1"
        ],
        "litellmPrefix": "openai",
        "isGateway": false,
        "defaultApiBase": "https://integrate.api.nvidia.com/v1",
        "envKey": "NVIDIA_API_KEY"
      }
    ]
  },
  "agents": {
    "defaults": {
      "model": "z-ai/glm4.7"
    }
  }
}
```

## 关键配置项

| 配置项 | 说明 | 必填 |
|--------|------|------|
| `name` | Provider唯一标识符 | 是 |
| `displayName` | 显示名称 | 否 |
| `apiKey` | API密钥 | 是 |
| `apiBase` | API基础URL | 是 |
| `models` | 支持的模型列表 | 是 |
| `litellmPrefix` | LiteLLM前缀（OpenAI兼容API设为"openai"） | 是 |
| `isGateway` | 是否为网关 | 否 |
| `defaultApiBase` | 默认API基础URL | 否 |
| `envKey` | 环境变量名称 | 否 |

## 重要提示

1. **OpenAI兼容API**：必须设置 `litellmPrefix: "openai"`
2. **模型名称**：在 `agents.defaults.model` 中直接使用模型名称，不需要加provider前缀
3. **API密钥安全**：不要将包含真实API密钥的配置文件提交到版本控制系统

## 常见问题

### Q: 为什么会出现404错误？

A: 检查以下几点：
- `apiBase` 是否正确
- 模型名称是否正确（区分大小写）
- 是否设置了 `litellmPrefix: "openai"`（对于OpenAI兼容API）

### Q: 如何验证配置是否正确？

A: 运行以下命令测试：
```bash
nanobot agent -m 你好
```

## 详细文档

完整的使用指南请参考：[docs/CUSTOM_PROVIDER_GUIDE.md](docs/CUSTOM_PROVIDER_GUIDE.md)

## 示例配置

更多配置示例请参考：[examples/custom_provider_config.json](examples/custom_provider_config.json)
