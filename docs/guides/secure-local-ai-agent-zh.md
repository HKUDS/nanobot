# 如何保护本地 nanobot AI Agent

本指南介绍在允许 nanobot agent 访问文件、shell 命令、网页抓取、聊天应用或远程用户之前，需要检查的实用控制措施。

## 你将构建的内容

- 工作区范围内的 agent 配置
- 受限的 channel 访问权限
- 更安全的密钥处理方式
- Linux 上可选的 shell 沙箱

## 适用场景

在将 nanobot 暴露给团队成员、聊天应用、公共网络、广泛的网页访问或无人值守的自动化任务之前使用本指南。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

## 最小可用示例

从限制工作区范围开始：

```json
{
  "tools": {
    "restrictToWorkspace": true,
    "exec": {
      "enable": true,
      "sandbox": "bwrap"
    }
  }
}
```

`bwrap` 仅适用于 Linux，并且需要 bubblewrap。在 macOS 或 Windows 上，保持启用
`restrictToWorkspace`，并仔细检查 shell 访问权限。

## 生产环境注意事项

- 使用环境变量存储 provider 密钥、bot token 和邮箱密码。
- 每个信任边界使用一个工作区。
- 对支持 DM 的聊天应用，优先使用配对；仅当静态允许列表是有意设计时才使用范围较窄的 `allowFrom` 列表，并在初期将群组策略保持为仅提及。
- 除非有意提供远程访问，否则将 WebUI、WebSocket 和 API 服务绑定到 localhost。

## 安全注意事项

- `restrictToWorkspace` 是应用层防护措施，不是 OS 沙箱。
- `tools.exec.enable: false` 会完全移除 shell 执行功能。
- HTTP 网页抓取和 HTTP MCP 默认使用 SSRF 防护。
- 添加范围过广的 `tools.ssrfWhitelist` 会扩大暴露面。
- `allowFrom: ["*"]` 会绕过配对，这意味着任何能够访问该 channel 的人都可以与 bot 对话。

## 故障排除

- 如果无法读取所需文件，请确认当前使用的工作区路径。
- 如果 shell 命令在 `bwrap` 下失败，请检查该命令是否需要访问沙箱外部的文件。
- 如果本地 HTTP 工具被阻止，请检查 SSRF 白名单并使用范围较窄的 CIDR。

## 相关 nanobot 文档

- [配置：安全性](../configuration-zh.md#security)
- [配对](../configuration-zh.md#pairing)
- [部署](../deployment-zh.md)
- [聊天应用](../chat-apps-zh.md)
