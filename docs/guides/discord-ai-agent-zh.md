# 使用 nanobot 构建 Discord AI Agent

本指南将 nanobot 连接到 Discord，使 Discord 用户或服务器频道能够通过
nanobot gateway 与你自行托管的 AI agent 对话。

## 本指南构建的内容

- Discord bot 应用
- 已启用 Message Content intent
- nanobot 中已启用 `discord` channel
- 一次私信或提及测试

## 前提条件

- 可正常运行的本地 nanobot 回复：

```bash
nanobot agent -m "Hello!"
```

- 可访问 Discord Developer Portal。
- 一个可以邀请 bot 的 Discord 服务器。

## 安装 nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## 启用 Discord channel

安装可选的 channel 依赖：

```bash
nanobot plugins enable discord
```

创建 Discord 应用，添加 bot，复制 token，并在 bot 设置中启用
`MESSAGE CONTENT INTENT`。

将此代码片段合并到 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowChannels": [],
      "groupPolicy": "mention",
      "streaming": true
    }
  }
}
```

省略 `allowFrom` 会启用仅配对模式。新用户应先向 bot 发送 DM，获取配对代码，
并在服务器中使用 bot 之前完成批准。

邀请 bot，并授予其读取历史记录和发送消息的权限。

## 运行 nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## 测试消息

先向 bot 发送 DM。它应返回配对代码。通过受信任的本地界面批准：

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

批准后，在允许的服务器频道中提及它：

```text
@your-bot Hello from Discord
```

## 安全注意事项

- 首次部署时，将 `groupPolicy` 保持为 `mention`。
- 使用 `allowChannels` 指定 bot 应运行的服务器频道。
- 对用户访问，优先使用仅配对模式；只有在需要静态 allowlist 时才添加
  `allowFrom`。
- 在会话路由明确之前，避免在繁忙频道中启用开放的群组行为。
- 将 bot 邀请到共享服务器之前，检查 tool 访问权限。

## 故障排除

- 如果没有收到消息，请确认已启用 Message Content intent。
- 如果 DM 返回配对代码，请先批准，然后测试正常回复。
- 如果服务器消息被忽略，请检查配对批准状态、`allowChannels`，以及是否提及了
  bot。
- 如果 bot 无法回复，请确认邀请权限和频道覆盖设置。

## 下一步：memory、automations、MCP tools

- [Chat Apps 参考](../chat-apps-zh.md)
- [配对](../configuration-zh.md#pairing)
- [AI Agent Memory](ai-agent-memory-zh.md)
- [配置 MCP tools](configure-mcp-tools-zh.md)
