# 如何使用 nanobot 构建个人 AI agent

本指南将构建一个可在本地运行的个人 AI agent，你可以通过
终端或浏览器与它对话，之后还可以连接聊天应用、memory、tool 和自动化功能。

## 你将构建什么

- 一个已配置的 nanobot 安装
- 一个可正常工作的 model provider
- 一条本地 agent 回复
- 一个用于持续工作的浏览器 WebUI session

## 适用场景

当你希望拥有一个由自己控制的个人 AI agent，而不是仅提供聊天功能的托管
界面时，可以使用本指南。当 agent 需要访问本地 workspace、调用 tool、保存
session 历史、使用 memory、执行计划任务或向聊天应用发送消息时，nanobot
非常有用。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

向导会创建 `~/.nanobot/config.json`，并帮助你选择 provider 和
model。如果你不熟悉终端和配置文件，请改用
[无技术背景也能开始](../start-without-technical-background-zh.md)。

## 最小可运行示例

首先验证运行时可以回答问题：

```bash
nanobot agent -m "Hello!"
```

然后打开浏览器工作台：

```bash
nanobot webui
```

WebUI 会启动本地 gateway、打开浏览器，并为较长时间的工作保留持久化的聊天
session。

## 生产环境注意事项

- 每个项目或个人上下文使用一个 workspace。
- 如果希望为快速、深度、本地或备用 model 使用稳定的名称，请使用
  `modelPresets`。
- 为 WebUI、聊天应用、自动化功能和 WebSocket channel 保持
  `nanobot gateway` 运行。
- 当其他程序需要调用 agent 时，请使用 Python SDK 或 OpenAI 兼容的 API。

## 安全注意事项

- 不要将 API 密钥直接存储在共享文件中；请使用环境变量。
- 首次设置时优先使用聊天应用配对。仅在需要静态允许列表时使用
  `allowFrom`，并将这些列表保持在最小范围内。
- 在向其他用户公开文件或 shell tool 之前，启用 workspace 限制。
- 对于可能修改文件的实验，使用单独的 workspace。

## 故障排除

- `nanobot status` 会显示配置路径、workspace 路径和当前 model。
- 如果 `nanobot agent -m "Hello!"` 失败，请先修复 provider 设置，再打开
  WebUI 或聊天应用。
- 如果 WebUI 能打开但不回答，请检查 gateway 日志和 provider
  凭据。

## 相关 nanobot 文档

- [快速开始](../quick-start-zh.md)
- [概念](../concepts-zh.md)
- [WebUI](../webui-zh.md)
- [配置](../configuration-zh.md)
- [故障排除](../troubleshooting-zh.md)
