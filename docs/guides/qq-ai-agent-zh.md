# 使用 nanobot 构建 QQ AI Agent

本指南通过官方 `qq` channel 将 nanobot 连接到 QQ。官方 channel 使用 botpy SDK，目前主要面向私信。对于 QQ 群聊和 OneBot v11 工作流，请参阅完整聊天应用参考中的 Napcat 部分。

## 本指南构建的内容

- 一个 QQ bot 应用
- nanobot 中启用的 `qq` channel
- 一个通过配对批准的 QQ 私信发送者
- 一个正在运行的 nanobot gateway

## 前提条件

- 本地 nanobot 回复正常：

```bash
nanobot agent -m "Hello!"
```

- QQ 开放平台访问权限。
- 一个已添加到 bot 沙箱环境中用于测试的 QQ 账号。

## 安装 nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## 启用 QQ channel

安装可选的 channel 依赖：

```bash
nanobot plugins enable qq
```

在 QQ 开放平台中创建一个 bot 应用，并复制 AppID 和 AppSecret。将你的 QQ 账号添加到沙箱测试成员中，然后将此代码片段合并到 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "msgFormat": "plain"
    }
  }
}
```

省略 `allowFrom` 会启用仅配对模式。新的私信发送者应先获得配对代码，然后才能正常访问 agent。

## 运行 nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## 测试消息

使用沙箱账号向 QQ bot 发送私信。它应返回一个配对代码。通过受信任的本地界面批准该代码：

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

批准后再次发送该消息。

## 安全注意事项

- 首次设置时优先使用仅配对模式。只有在需要静态允许列表时才添加 `allowFrom`。
- 将沙箱测试与生产发布分开。
- 对于已部署的服务，通过环境变量存储 QQ AppSecret。
- 只有在明确需要 QQ 账号桥接和群聊功能时才使用 Napcat。

## 故障排除

- 如果收不到私信，请确认发送者位于 QQ bot 沙箱中，并且 gateway 正在运行。
- 如果输出格式不可靠，请将 `msgFormat` 保持为 `"plain"`。
- 如果首次私信返回配对代码，请在测试正常回复前批准该代码。
- 如果需要 QQ 群组，请参阅完整聊天应用参考中的 Napcat 部分。

## 下一步：memory、自动化和 MCP tools

- [聊天应用参考](../chat-apps-zh.md)
- [配对](../configuration-zh.md#pairing)
- [AI Agent Memory](ai-agent-memory-zh.md)
- [配置 MCP tools](configure-mcp-tools-zh.md)
