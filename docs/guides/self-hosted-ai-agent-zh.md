# 如何使用 nanobot 运行自托管 AI Agent

本指南将 nanobot 设置为在您自己的机器或服务器上运行的自托管 AI Agent
运行时。最终结果是一个 gateway 进程，可以为 WebUI、聊天应用、自动化任务和
API 集成提供服务。

## 您将构建的内容

- 由您控制的 nanobot 配置和 workspace
- 通过 `config.json` 连接的 model provider
- 长时间运行的 `nanobot gateway`
- 可选的浏览器、聊天应用和 API 访问

## 适用场景

当您希望由本地或服务器端管理 Agent 进程、workspace 文件、memory 文件和
provider 密钥时，请使用此方式。当 Agent 必须在某条终端命令结束后继续运行时，
这也是正确的方式。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

在部署 gateway 之前完成 CLI 检查。已知 provider 和 model 可以正常工作后，
部署问题会更容易调试。

## 最小可运行示例

对于聊天应用、自动化任务和 WebSocket 传输，请启动 gateway：

```bash
nanobot gateway
```

对于浏览器界面，请改用 WebUI 启动器。它可以为您启动并管理本地 gateway：

```bash
nanobot webui
```

或者在 `~/.nanobot/config.json` 中连接一个 channel，然后让同一个 gateway
进程持续运行以接收消息。

## 生产环境说明

- 当进程需要在终端退出后继续运行时，请使用 Docker、systemd 或 macOS LaunchAgent。
- 为每个已部署的实例指定不同的配置路径、workspace 路径和端口集合。
- 将密钥保存在环境变量中，并从相同的环境启动服务。
- 对 gateway 或 API 进程执行健康检查，不要只将聊天应用的消息传递作为唯一信号。

## 安全说明

- 除非您有意将服务公开，否则请将仅限本地的服务绑定到 `127.0.0.1`。
- 在将 OpenAI 兼容 API 绑定到公共接口之前设置 API 密钥。
- 对支持 DM 的聊天应用优先使用配对，并严格限制任何静态的 `allowFrom` 允许列表。
- 启用 `tools.restrictToWorkspace`；在 Linux 上，对 shell 执行使用 bubblewrap sandbox。

## 故障排除

- 使用服务所用的相同 `--config` 和 `--workspace` 标志运行 `nanobot status`。
- 调试 channel 启动时运行 `nanobot gateway --verbose`。
- 如果 WebUI、WebSocket channel 或 API 端点无法绑定，请检查端口冲突。

## 相关 nanobot 文档

- [部署](../deployment-zh.md)
- [多个实例](../multiple-instances-zh.md)
- [配置](../configuration-zh.md)
- [聊天应用](../chat-apps-zh.md)
- [OpenAI 兼容 API](../openai-api-zh.md)
