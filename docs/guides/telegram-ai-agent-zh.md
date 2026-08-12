# 将 Telegram 连接到 nanobot

本指南将一个 Telegram bot 连接到 nanobot。发送到该 bot 的消息会使用你
正常的 nanobot model、tool、memory 和 workspace。

## 本指南构建的内容

- 通过 BotFather 创建的 Telegram bot
- 在 nanobot 中启用的 `telegram` channel
- 正在运行的 nanobot gateway
- 一个已通过 pairing 批准的 Telegram 账号

## 前提条件

- 可正常工作的 nanobot CLI 回复：

```bash
nanobot agent -m "Hello!"
```

- 一个 Telegram 账号。
- 从 `@BotFather` 获取的 bot token。

## 安装 nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## 在 WebUI 中连接 Telegram

启动 WebUI：

```bash
nanobot webui
```

打开 **设置 → Channels → Telegram**：

1. 如果尚未安装 Telegram 支持，请打开其开关并确认安装。
2. 粘贴 BotFather 提供的 token。
3. 如果 gateway 无法直接连接 Telegram，请展开 **高级**，并输入 HTTP 或 SOCKS proxy，例如
   `http://127.0.0.1:7890`。
4. 保存并启用 Telegram。

保存 bot token 后，配置标记会立即显示。连接检查是独立进行的：如果 Telegram 暂时无法访问，已保存的
配置仍然有效，并且 bot 可以继续在 gateway 具备网络访问权限的环境中工作。

已保存的 token 和 proxy URL 会被隐藏。此处输入的 proxy 同时用于连接检查和正常的 Telegram 流量。

## 手动设置

对于无头安装，请安装 Telegram 支持：

```bash
nanobot plugins enable telegram
```

然后将此代码片段合并到 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

当 gateway 可以直接连接 Telegram 时，省略 `proxy`。

省略 `allowFrom` 会启用仅 pairing 模式。新用户发送的第一条 DM 会获得 pairing code，而不是 agent 访问权限。

Telegram 默认使用 long polling。Webhook 模式可用于公开的
HTTPS 部署；首次测试时请从 long polling 开始。

## 运行 nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

测试消息期间保持 gateway 运行。

## 测试消息

打开 Telegram，向 bot 发送 DM，并发送：

```text
Hello from Telegram
```

bot 应该会回复一个 pairing code。从已信任的 surface（例如本地 CLI）批准该 code：

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

批准后再次发送该消息。回复应该使用与你的本地 CLI 检查相同的 model 和
workspace。

## 安全说明

- 首次设置时建议使用仅 pairing 模式。只有在希望使用静态 allowlist 而不是 code approval 时，才添加
  `allowFrom`。
- 除非 bot 已隔离或有意公开，否则不要使用 `allowFrom: ["*"]`。
- 如果 BotFather token 被粘贴到日志或共享文件中，请轮换该 token。
- 添加群聊或更多用户之前，请检查 tool 访问权限。

## 故障排除

- 如果列表中没有该 channel，请在同一个 Python 环境中再次运行
  `nanobot plugins enable telegram`。
- 如果 WebUI 显示已保存的配置，但实时检查无法连接 Telegram，
  token 仍然已保存。确认 gateway 可以访问 `api.telegram.org`，
  或打开 **高级 → Network proxy** 并输入 proxy。
- 如果 Telegram 拒绝该 token，请从 BotFather 复制当前 token，或重新生成 token。
- 如果收不到消息，请运行 `nanobot gateway --verbose`，并确认
  Telegram channel 已启用。
- 如果首次 DM 返回 pairing code，这是预期行为。测试正常的 agent 回复之前，请先批准该 code。
- 如果 Telegram Web 显示不支持 rich messages，请保持 `richMessages` 禁用。

## 下一步：memory、automations、MCP tools

- [Chat Apps 参考](../chat-apps-zh.md)
- [AI Agent Memory](ai-agent-memory-zh.md)
- [Long-running AI Agent](long-running-ai-agent-zh.md)
- [配置 MCP tools](configure-mcp-tools-zh.md)
