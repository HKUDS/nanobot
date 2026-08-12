# 使用 nanobot 构建 WhatsApp AI Agent

本指南通过 `whatsapp` channel 将 nanobot 连接到 WhatsApp。该 channel 作为 WhatsApp 设备进行链接，并使用与 CLI 和 WebUI 相同的 nanobot agent runtime、tools、memory 和 workspace。

## 本指南将构建的内容

- 已安装 WhatsApp 可选依赖
- 一个已链接的 WhatsApp 设备 session
- 已在 `config.json` 中启用 `whatsapp` channel
- 一个已通过配对批准的 WhatsApp sender

## 前提条件

- 可正常工作的本地 nanobot 回复：

```bash
nanobot agent -m "Hello!"
```

- 一个能够链接新设备的 WhatsApp 账户。
- 一台能够持续运行 `nanobot gateway` 的机器。

## 安装 nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## 启用 WhatsApp channel

安装可选的 channel 依赖：

```bash
nanobot plugins enable whatsapp
```

将 WhatsApp 作为设备进行链接：

```bash
nanobot channels login whatsapp
```

在 WhatsApp 中依次进入 设置 -> 已链接设备，并扫描 QR code。

将以下片段合并到 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "groupPolicy": "mention"
    }
  }
}
```

省略 `allowFrom` 会为私聊启用仅配对模式。channel 中的 `groupPolicy`
默认值为 `"open"`，但对于首次部署，使用 `"mention"` 更安全。

## 运行 nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## 测试消息

向 bot 发送一条私有 WhatsApp 消息。它应返回一个配对代码。
从受信任的本地界面批准它：

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

批准后再次发送消息。回复应使用与本地 CLI 检查相同的 model 和
workspace。

## 安全说明

- 将 WhatsApp session 数据库视为账户访问凭据。
- 首次设置时优先使用仅配对模式。仅当需要静态 allowlist 时再添加 `allowFrom`。
- 将 bot 添加到群组之前，保持 `groupPolicy` 为 `"mention"`。
- 除非 bot 有意公开或处于隔离状态，否则避免使用 `allowFrom: ["*"]`。

## 故障排除

- 如果 QR 链接失败，请重新运行 `nanobot channels login whatsapp`。
- 如果要从旧 bridge 迁移，请移除 `bridgeUrl` 和
  `bridgeToken`，然后重新登录。
- 如果 sender 显示为 LID 而非电话号码，请让 nanobot 在 runtime 时学习该
  mapping，或使用完整参考中的 `lidMappings`。
- 如果第一条私有消息返回配对代码，请先批准它，再测试正常回复。

## 下一步：memory、automations、MCP tools

- [聊天应用参考](../chat-apps-zh.md)
- [配对](../configuration-zh.md#pairing)
- [安全的本地 AI agent](secure-local-ai-agent-zh.md)
- [部署](../deployment-zh.md)
