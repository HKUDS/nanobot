# 如何为 nanobot 配置 Langfuse Observability

nanobot 可以通过 Langfuse 的 OpenAI SDK wrapper 跟踪受支持的 OpenAI-compatible provider 调用。

## 你将完成的内容

- 在与 nanobot 相同的 Python 环境中安装 Langfuse
- 在启动前设置 Langfuse 环境变量
- 一次已跟踪的 nanobot model 调用

## 适用场景

当你在开发或生产运行期间需要了解 model 请求、延迟、错误、成本或 prompt 行为时，请使用 Langfuse。

## 安装

安装 nanobot 并验证 agent 可以工作：

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

安装 Langfuse：

```bash
nanobot plugins enable langfuse
```

## 最小可用示例

在启动 nanobot 前设置凭据：

```bash
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
nanobot agent -m "Hello!"
```

PowerShell：

```powershell
$env:LANGFUSE_SECRET_KEY = "sk-lf-..."
$env:LANGFUSE_PUBLIC_KEY = "pk-lf-..."
$env:LANGFUSE_BASE_URL = "https://cloud.langfuse.com"
nanobot agent -m "Hello!"
```

## 生产说明

- Langfuse 通过环境变量配置，而不是 `config.json`。
- 从导出了相同变量的环境中启动服务。
- 在 provider 正常工作后再添加跟踪；它不应是第一个配置步骤。
- 不使用 OpenAI-compatible client 路径的原生 provider 可能不会生成 Langfuse OpenAI-wrapper 跟踪。

## 安全说明

- 将 Langfuse 项目视为用于存储敏感 prompt 和输出的 observability 存储。
- 为个人、staging 和生产流量使用独立项目。
- 不要将 Langfuse 密钥提交到 service 文件中。

## 故障排除

- 如果没有出现跟踪，请确认 service 进程能读取到环境变量。
- 确认 provider 路径为 OpenAI-compatible。
- 在调试 service 日志前，先运行一次本地 `nanobot agent -m "Hello!"` 调用。

## 相关 nanobot 文档

- [配置：Langfuse Observability](../configuration-zh.md#langfuse-observability)
- [Provider Cookbook：Langfuse Tracing](../provider-cookbook-zh.md#recipe-langfuse-tracing)
- [部署](../deployment-zh.md)
