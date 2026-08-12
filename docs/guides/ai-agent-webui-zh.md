# 如何将 AI Agent WebUI 与 nanobot 一起使用

nanobot 包含一个浏览器 WebUI，用于持久化聊天 session、可见的 agent
活动、workspace 控制、Apps、MCP 预设、Skills、设置和
Automations。

## 您将构建的内容

- 一个本地浏览器工作台
- 一个持久化聊天 session
- 一个可见的 agent 消息、tool 调用和文件编辑 diff 时间线
- 一个由 gateway 支持的 WebSocket 连接

## 何时使用

当您希望使用比终端更易于操作的本地 AI agent 界面时，请使用 WebUI，
尤其适用于项目工作、文件附件、model 切换、workspace 选择、Apps、Skills
和定时 automations。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

已发布的 wheel 已包含 WebUI bundle。仅在修改前端时才需要
`webui/` 源目录。

## 最小可用示例

```bash
nanobot webui
```

启动器会检查设置，在确认后启用本地 WebSocket channel，启动 gateway，
并打开浏览器。

当 nanobot 编辑文件时，WebUI 活动时间线可以显示变更的行数、统一 diff，
以及用于只读预览的 **打开文件** 操作。文件预览使用聊天当前的 workspace
访问模式：受限访问会保留在选定的 workspace 内，而 Full Access 可以在
gateway 允许时预览 workspace 外的文件。

## 生产环境说明

- 当您不想保持终端打开时，请使用 `nanobot webui --background`。
- 使用 `nanobot gateway status`、`logs`、`restart` 和 `stop` 管理
  后台 gateway。
- 如果您将 WebUI 暴露到 localhost 之外，请设置 token 签发 secret，并审查
  workspace/tool 访问权限。

## 安全说明

- 首次运行的 WebUI 路径默认绑定到 `127.0.0.1`。
- 在没有明确访问模型的情况下，请勿将 WebUI 暴露在 LAN 或公共主机上。
- 在邀请其他用户之前，请将文件和 shell tools 的范围限制在 workspace 内。

## 故障排除

- WebUI 默认由端口 `8765` 上的 WebSocket channel 提供服务。
- gateway 健康检查 endpoint 与浏览器 UI 相互独立。
- 如果页面能够打开但消息发送失败，请使用
  `nanobot agent -m "Hello!"` 检查 provider 设置。

## 相关 nanobot 文档

- [Nanobot WebUI](../webui-zh.md)
- [快速开始](../quick-start-zh.md)
- [WebSocket 协议](../websocket-zh.md)
- [配置](../configuration-zh.md)
