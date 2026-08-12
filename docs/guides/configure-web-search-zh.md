# 如何为 nanobot AI Agent 配置 Web 搜索

nanobot 包含内置的 web 搜索和 web 抓取 tool。搜索默认使用
DuckDuckGo，并且可配置为使用由 API 支持或自托管的
provider。

## 你将构建的内容

- 在 nanobot 中启用 web tool
- 在 WebUI 或 `config.json` 中选择一个搜索 provider
- 用于页面读取的可选 web 抓取设置

## 何时使用

当 agent 在任务期间需要当前信息、公开 web
研究、来源发现或页面抓取时，配置 web 搜索。

## 安装

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

web tool 默认已启用。仅当你需要特定
provider、API key、proxy、抓取行为或 SSRF allowlist 时配置它们。

## 最小可用示例

对于本地交互式设置：

1. 运行 `nanobot webui`。
2. 打开 **Settings → Web**。
3. 启用 web 搜索，选择一个 provider，并在需要时输入其 API key。
4. 保存，并在提示时重启。
5. 提出一个需要当前信息的问题，并检查引用的来源。

对于手动或由部署管理的 config，请使用默认搜索 provider：

```json
{
  "tools": {
    "web": {
      "enable": true,
      "search": {
        "provider": "duckduckgo"
      }
    }
  }
}
```

或者使用由 API 支持的 provider：

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "${BRAVE_API_KEY}"
      }
    }
  }
}
```

提出一个需要当前信息的问题，并在 WebUI 或日志中检查 tool 活动。

## 生产环境说明

- 将 API key 保留在环境变量中。
- 当每个查询需要更少或更多搜索结果时，设置 `maxResults`。
- 仅将 `tools.web.proxy` 设置为你信任的 proxy。
- 如果需要本地页面转换，请使用 `fetch.useJinaReader: false`。

## 安全说明

- Web 抓取和 HTTP MCP 共用一个 SSRF guard。
- 默认会阻止私有、loopback、link-local 和 cloud metadata 地址。
- 仅为范围较小且可信的 CIDR 添加 `tools.ssrfWhitelist`。
- 未经审查，不要向公开 chat 用户提供不受限制的 web 和 shell 访问权限。

## 故障排除

- 如果搜索未返回结果，请切换 provider 或检查 provider API key。
- 如果抓取被阻止，请检查目标 URL 和 SSRF whitelist。
- 如果 proxy 改变了网络行为，请验证 `NO_PROXY` 和 proxy 设置。

## 相关 nanobot 文档

- [配置：Web Tools](../configuration-zh.md#web-tools)
- [安全](../configuration-zh.md#security)
- [WebUI](../webui-zh.md)
