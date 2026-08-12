# 如何在 nanobot 中配置 MCP 工具

本指南将 MCP 服务器添加到 nanobot，使 agent 能够通过模型上下文协议使用外部工具。

## 你将构建的内容

- 一个可正常工作的 nanobot agent
- 一个通过 Apps 或 `~/.nanobot/config.json` 配置的 MCP 集成
- 一组向 model 暴露的受限 MCP 工具

## 何时使用

当你需要的能力已经作为 MCP 服务器存在，或者希望在 nanobot 核心之外管理外部工具时，请使用 MCP。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

单独安装 MCP 服务器运行时。许多示例使用 `npx`、`uvx` 或远程 HTTP 端点。

## 最小可用示例

对于本地交互式设置：

1. 运行 `nanobot webui` 并打开 **Apps**。
2. 选择已知的集成预设，或添加自定义 stdio、HTTP 或 SSE 服务器。
3. 当服务器暴露的工具多于任务所需时，限制已启用的工具。
4. 按提示保存并重启。
5. 在下一条消息中使用 `@` 提及该集成，并请求执行一个小型测试操作。

对于手动配置或由部署管理的配置，将以下内容添加到 `~/.nanobot/config.json`：

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
        "enabledTools": ["read_file"]
      }
    }
  }
}
```

重启 nanobot，并提出一个需要使用 MCP 工具的问题。

## 生产环境注意事项

- 优先使用 `enabledTools`，而不是默认暴露所有工具。
- 对于运行缓慢的 MCP 操作，使用 `toolTimeout`。
- 仅对你信任的端点使用 HTTP MCP。
- 在部署文档或脚本中保持 MCP 服务器命令稳定并进行版本管理。

## 安全注意事项

- Stdio MCP 会启动本地进程；启用前请检查该命令。
- HTTP/SSE MCP 使用 nanobot 的 SSRF 防护。
- 仅在 `tools.ssrfWhitelist` CIDR 范围足够严格时，允许私有 HTTP MCP 主机。
- 当可以使用环境变量或请求头时，不要将机密信息放在命令参数中。

## 故障排除

- 先在 nanobot 外部运行 MCP 命令。
- 启动 `nanobot gateway --verbose`，并检查工具注册日志。
- 如果 HTTP MCP URL 被阻止，请检查它是否指向回环地址，或指向需要显式加入允许列表的私有地址。

## 相关 nanobot 文档

- [面向 AI agent 的 MCP 工具](mcp-tools-for-ai-agents-zh.md)
- [配置：MCP](../configuration-zh.md#mcp-model-context-protocol)
- [安全](../configuration-zh.md#security)
