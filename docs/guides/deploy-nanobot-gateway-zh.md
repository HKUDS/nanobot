# 如何部署长期运行的 nanobot AI Agent gateway

nanobot gateway 是一个长期运行的自托管 AI agent 进程，用于保持
WebUI 会话、聊天应用、自动化任务、本地触发器、heartbeat 作业、Dream
和 WebSocket 传输在线。

## 你将构建的内容

- 已验证的 nanobot 配置
- gateway 进程
- 使用 Docker、systemd 或 macOS
  LaunchAgent 的服务或容器部署路径

## 适用场景

当 nanobot 需要在单次 CLI 操作结束后继续运行时，请使用此方式。聊天应用、
浏览器会话、后台自动化任务、本地触发器和服务端集成都依赖于处于运行状态的 gateway。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot status
nanobot agent -m "Hello!"
```

## 最小可运行示例

在前台运行 gateway：

```bash
nanobot gateway
```

用于 WebUI 后台运行：

```bash
nanobot webui --background
nanobot gateway status
nanobot gateway logs
```

## 生产环境说明

- Docker Compose 是最具可重复性的 Linux 容器部署方式。
- systemd 用户服务适用于 Linux 用户级 gateway 部署。
- macOS LaunchAgent 可使 gateway 在登录后保持运行。
- 持久化配置、workspace、会话、memory 文件、channel 登录状态和生成的构件。
- 编辑 `config.json` 后重启 gateway。

## 安全说明

- 在公开服务之前规划端口。gateway 健康检查默认为 `18790`，
  WebUI/WebSocket 默认为 `8765`，`nanobot serve` 默认为 `8900`。
- 只有在配置了令牌或 API 密钥后，才绑定到外部地址。
- 部署前明确配置聊天访问控制。
- 启用 shell 工具执行无人值守任务时，使用 Docker 或 Linux 沙箱。

## 故障排除

- 对状态检查和服务启动使用相同的 `--config` 和 `--workspace` 标志。
- 使用 `docker compose logs`、`journalctl`、LaunchAgent 日志或
  `nanobot gateway --verbose` 检查日志。
- 如果 Docker 端口发布不起作用，请确认服务并非仅绑定到容器回环地址。

## 相关 nanobot 文档

- [部署](../deployment-zh.md)
- [多实例](../multiple-instances-zh.md)
- [配置](../configuration-zh.md)
