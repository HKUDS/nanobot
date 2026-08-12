# nanobot 文档

请先使用这些文档让智能体运行起来，然后仅在需要下一项能力时再打开相应的任务指南。源代码级别的设计和扩展细节保存在贡献者部分。

仓库文档遵循当前源代码树，可能比最新的软件包版本更新。有关已发布版本的文档，请访问 [nanobot.wiki](https://nanobot.wiki/docs/latest/getting-started/nanobot-overview)。

## 从这里开始

| 你的情况 | 阅读此文档 | 满足以下条件即完成... |
|---|---|---|
| 你刚接触终端、Python 或 API 密钥 | [新手演练](start-without-technical-background-zh.md) | 浏览器可以发送 `Hello!` 并收到回复 |
| 你熟悉运行命令 | [安装和快速开始](quick-start-zh.md) | `nanobot status` 状态正常，且 WebUI 或 CLI 可以获得一条回复 |
| 已经有操作失败 | [故障排除](troubleshooting-zh.md) | 你已将问题定位到安装、配置、模型、网关、渠道或工具访问 |

推荐的首次运行路径：

1. 安装 nanobot。
2. 让安装程序在新的本地桌面上打开 `nanobot webui`。
3. 在 **设置 → 模型** 中配置提供商和模型。
4. 在配置其他任何内容之前发送 `Hello!`。

大多数人在首次运行时无需编辑 JSON。WebUI 会处理初始提供商、模型和本地浏览器设置。对于 SSH、无头环境、已有配置或旧版本安装，仍可使用 `nanobot onboard --wizard` 作为终端后备方案。WebUI 打开后，使用 **设置** 配置模型和内置能力，使用 **设置 → 渠道** 配置聊天应用，使用 **应用** 配置 CLI App 或 MCP 集成。

## 添加一项能力

选择与你接下来想完成的事项相匹配的行：

| 目标 | 指南 |
|---|---|
| 学习浏览器工作台 | [WebUI](webui-zh.md) |
| 连接 Telegram、Discord、Slack、Feishu、WeChat、Email 或其他聊天应用 | [聊天应用](chat-apps-zh.md) |
| 选择托管、OAuth、公司或本地模型 | [提供商指南](provider-cookbook-zh.md) |
| 添加模型后备方案 | [配置模型后备](guides/configure-model-fallback-zh.md) |
| 启用网页搜索 | [配置网页搜索](guides/configure-web-search-zh.md) |
| 添加 MCP 工具服务器 | [配置 MCP 工具](guides/configure-mcp-tools-zh.md) |
| 生成图像 | [图像生成](image-generation-zh.md) |
| 安排工作或创建本地触发器 | [自动化](automations-zh.md) |
| 了解并管理长期记忆 | [记忆](memory-zh.md) |
| 持续运行 nanobot | [部署](deployment-zh.md) |
| 运行独立的机器人或工作区 | [多个实例](multiple-instances-zh.md) |
| 从 Python 调用 nanobot | [Python SDK](python-sdk-zh.md) |
| 暴露 OpenAI 兼容端点 | [OpenAI 兼容 API](openai-api-zh.md) |

如需更简短、以结果为导向的演练，请浏览[任务指南索引](guides/README-zh.md)。

## 运行 nanobot

| 需求 | 阅读 |
|---|---|
| 命令和标志 | [CLI 参考](cli-reference-zh.md) |
| 聊天内斜杠命令 | [聊天内命令](chat-commands-zh.md) |
| 用通俗语言了解配置、工作区、网关、会话、工具和记忆 | [概念](concepts-zh.md) |
| 提供商/模型匹配和选择 | [提供商和模型](providers-zh.md) |
| 设置和运行时诊断 | [故障排除](troubleshooting-zh.md) |
| 较早的开发亮点 | [发布归档](release-archive-zh.md) |

## 参考

在明确要配置的内容后，使用参考页面查找确切的选项：

| 范围 | 参考 |
|---|---|
| 每个配置字段和默认值 | [配置](configuration-zh.md) |
| 提供商和模型行为 | [提供商和模型](providers-zh.md) |
| 聊天渠道前置条件和手动 JSON | [聊天应用](chat-apps-zh.md) |
| WebSocket 身份验证和传输协议 | [WebSocket](websocket-zh.md) |
| Python SDK 类、事件、会话和钩子 | [Python SDK](python-sdk-zh.md) |
| OpenAI 兼容 HTTP 路由和负载 | [OpenAI 兼容 API](openai-api-zh.md) |
| 运行时自检和调优 | [My Tool](my-tool-zh.md) |

配置示例通常是要合并到 `~/.nanobot/config.json` 的片段，而不是完整的替换文件。文档使用 camelCase，因为 nanobot 会以这种方式写入配置。请不要将真实 API 密钥、机器人令牌和密码提交到 issue 或公开日志中。

## 扩展或贡献

这些页面说明实现和扩展点。安装或运行 nanobot 时不需要阅读它们。

| 目标 | 阅读 |
|---|---|
| 了解源代码所有权和运行时流程 | [架构](architecture-zh.md) |
| 设置开发环境 | [开发](development-zh.md) 和 [CONTRIBUTING.md](../CONTRIBUTING.md) |
| 添加渠道包 | [渠道包指南](channel-package-guide-zh.md) |
| 构建 WebUI 源代码 | [WebUI 开发](../webui/README.md) |

如果命令或界面不再与这些文档相符，请通过[提交 issue](https://github.com/HKUDS/nanobot/issues)提供你的 nanobot 版本、操作系统以及需要修正的页面。
