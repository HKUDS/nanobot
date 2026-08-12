# 如何使用 nanobot 向 AI agent 添加 MCP 工具

nanobot 可以连接 MCP 服务器，并将其工具与内置的文件、shell、Web、cron、图像生成和子 agent 工具一起提供给 agent。

## 你将构建的内容

- 一个可运行的 nanobot agent
- 在 `config.json` 中配置的一个 MCP 服务器
- 一组提供给 model 的受限工具

## 适用场景

当某个工具已经作为 MCP 服务器存在、其他应用发布了 MCP 适配器，或者你希望在 nanobot 与外部工具逻辑之间建立清晰的边界时，可以使用 MCP。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

请单独安装 MCP 服务器自身的运行时。例如，许多本地 MCP 服务器使用 `npx` 或 `uvx`。

## 最小可运行示例

将一个 stdio MCP 服务器添加到 `~/.nanobot/config.json`：

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

重启 nanobot，然后提出一个需要使用 MCP 工具的问题。

## 生产环境注意事项

- 使用 `enabledTools` 仅提供 agent 实际需要的工具。
- 为运行缓慢的 MCP 服务器设置 `toolTimeout`。
- 对于本地工具，优先使用 stdio MCP；对于受信任的远程服务，优先使用 HTTP MCP。
- 尽可能将 MCP 服务器的安装和更新步骤置于 nanobot 配置之外。

## 安全注意事项

- HTTP/SSE MCP URL 使用与 Web fetch 相同的 SSRF 防护。
- 本地或私有 HTTP 端点需要显式的 `tools.ssrfWhitelist` 条目。
- Stdio MCP 服务器会运行本地进程；请检查其命令和参数。
- 当环境变量或标头可用时，不要将机密信息作为命令行参数传递。

## 故障排除

- 启动 `nanobot gateway --verbose`，并检查 MCP 启动日志。
- 在调试 nanobot 之前，先确认 MCP 命令本身可以正常运行。
- 如果 HTTP MCP 服务器被阻止，请检查 SSRF 白名单，并使用范围较窄的主机 CIDR。

## 相关 nanobot 文档

- [配置 MCP 工具](configure-mcp-tools-zh.md)
- [配置：MCP](../configuration-zh.md#mcp-model-context-protocol)
- [安全](../configuration-zh.md#security)
