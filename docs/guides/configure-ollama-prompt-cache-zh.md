# 如何改进 nanobot 中 Ollama 工具调用的提示缓存复用

某些 Ollama 模型模板会在对话在 user、assistant 和 tool 消息之间切换时移动或移除工具定义。nanobot 可以发送正确的仅追加式聊天请求，但模型模板仍可能渲染出不同的 token 前缀。在较慢的本地硬件上，重新评估此前缀可能会为原本简单的工具调用轮次增加数十秒。

本指南介绍如何诊断这一特定模式，并创建一个带有前缀稳定工具模板的派生 `llama3.1:8b` 标签。它不会修改 nanobot，也不会覆盖原始 Ollama 模型。

## 你将构建的内容

- 可重复执行的两轮缓存检查
- 可选的派生 `llama3.1:8b-prefix-stable-v1` Ollama 标签
- 使用派生标签的 nanobot 模型预设

## 适用场景

当以下所有条件都满足时，请使用本指南：

- 直接的 Ollama 响应速度合理；
- nanobot 在模型调用工具后变慢；
- Ollama 日志显示较长的主提示、短得多的工具后续请求，以及下一条主提示较低的初始缓存复用率；
- 模型是 `llama3.1:8b`，并使用了仅在最后一条 user 消息中渲染具体工具的模板。

在未先检查其他模型系列的工具调用格式之前，不要将此模板应用于其他模型系列。

## 诊断渲染后的提示

停止任何现有的 Ollama 进程，然后启动单槽调试服务器。单个槽位可以让缓存序列更易于读取。

**macOS 或 Linux**

```bash
OLLAMA_CONTEXT_LENGTH=16384 \
OLLAMA_NUM_PARALLEL=1 \
OLLAMA_DEBUG=1 \
ollama serve
```

**Windows PowerShell**

```powershell
$env:OLLAMA_CONTEXT_LENGTH = "16384"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_DEBUG = "1"
ollama serve
```

在另一个终端中，使用一个新 session，并明确请求一个工具，以便两轮都执行 agent 循环：

```bash
nanobot agent --session cli:ollama-cache-check \
  --message "Use the exec tool to calculate 2+2, then answer"
nanobot agent --session cli:ollama-cache-check \
  --message "Use the exec tool to calculate 4+7, then answer"
```

在 Ollama 输出中，找到每一条 `new prompt` 行，以及其后出现的第一条
`cached n_tokens` 行。之后递增的 `cached n_tokens` 行表示提示评估进度，而不是额外的初始缓存命中。

不利于缓存的工具模板可能会产生如下模式：

```text
turn 1 main:             2 / 8460 initially cached
turn 1 tool follow-up: 3713 / 3758 initially cached
turn 2 main:          3767 / 8519 initially cached
```

缓存正在工作，但下一条主请求只能复用较短的提示。剩余评估的开销取决于硬件吞吐量。

如需同时检查 API 请求正文，请在启动 Ollama 前添加
`OLLAMA_DEBUG_LOG_REQUESTS=1`。这些日志可能包含 system 提示、workspace 上下文和 user 消息。请将其保留在本地，并在诊断完成后禁用请求日志记录。

## 这为什么会在默认模板中发生

经过测试的 `llama3.1:8b` 模板会在 user 消息内有条件地展开工具定义：

```gotemplate
{{- if and $.Tools $last }}
  ... render tool definitions ...
{{- end }}
```

第一条请求以 user 消息结束，因此工具会在该处渲染。nanobot 追加 assistant tool call 及其结果后，该 user 消息不再是最后一条消息，因此相同的 API 请求历史会渲染为不包含具体工具块。在下一轮 user 消息中，工具会重新出现在新的位置。

这是模型模板的行为。在 API 边界上，nanobot 仍会追加 assistant tool call 和 tool result，并发送相同的工具定义。

## 创建前缀稳定的派生模型

创建 `PrefixStable.Modelfile`，内容如下。该模板将具体工具定义保留在 system 块中，因此它们在 user 消息和 tool 消息之间始终位于相同位置。

```dockerfile
FROM llama3.1:8b

TEMPLATE """{{- if or .System .Tools }}<|start_header_id|>system<|end_header_id|>
{{- if .System }}

{{ .System }}
{{- end }}
{{- if .Tools }}

Cutting Knowledge Date: December 2023

When you receive a tool call response, use the output to format an answer to the original user question.

You are a helpful assistant with tool calling capabilities.

Given the following functions, respond with a JSON function call with the proper arguments when a tool is needed.

Respond in the format {"name": function name, "parameters": dictionary of argument name and its value}. Do not use variables.

{{ range .Tools }}
{{- . }}
{{ end }}
{{- end }}<|eot_id|>
{{- end }}
{{- range $i, $_ := .Messages }}
{{- $last := eq (len (slice $.Messages $i)) 1 }}
{{- if eq .Role "user" }}<|start_header_id|>user<|end_header_id|>

{{ .Content }}<|eot_id|>{{ if $last }}<|start_header_id|>assistant<|end_header_id|>

{{ end }}
{{- else if eq .Role "assistant" }}<|start_header_id|>assistant<|end_header_id|>
{{- if .ToolCalls }}
{{ range .ToolCalls }}
{"name": "{{ .Function.Name }}", "parameters": {{ .Function.Arguments }}}{{ end }}
{{- else }}

{{ .Content }}
{{- end }}{{ if not $last }}<|eot_id|>{{ end }}
{{- else if eq .Role "tool" }}<|start_header_id|>ipython<|end_header_id|>

{{ .Content }}<|eot_id|>{{ if $last }}<|start_header_id|>assistant<|end_header_id|>

{{ end }}
{{- end }}
{{- end }}"""
```

创建新标签：

```bash
ollama create llama3.1:8b-prefix-stable-v1 -f PrefixStable.Modelfile
ollama list
```

Ollama 会复用现有的模型层。新标签只会添加一个小型模板和清单，而不会复制基础权重。

## 在 nanobot 中选择派生模型

将此预设合并到 `~/.nanobot/config.json`，然后选择它：

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434/v1"
    }
  },
  "modelPresets": {
    "ollamaPrefixStable": {
      "label": "Ollama Llama 3.1 prefix-stable",
      "provider": "ollama",
      "model": "llama3.1:8b-prefix-stable-v1",
      "maxTokens": 2048,
      "contextWindowTokens": 16384,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "ollamaPrefixStable"
    }
  }
}
```

验证所选模型，然后重复两轮检查：

```bash
nanobot status
nanobot agent --session cli:ollama-stable-check \
  --message "Use the exec tool to calculate 2+2, then answer"
nanobot agent --session cli:ollama-stable-check \
  --message "Use the exec tool to calculate 4+7, then answer"
```

在一次使用 Ollama 0.32.1、`llama3.1:8b` 和单个槽位的受控测试中，第二条主请求的初始缓存量从
`3767 / 8519`（44.22%）提升到 `8505 / 8520`（99.82%）。重新评估的 token 数量从 4752 降至 15。请将这些数字视为诊断示例，而不是性能保证。

## 回滚

将 `agents.defaults.modelPreset` 切换回原始预设。当没有任何配置使用派生标签时，使用以下命令将其删除：

```bash
ollama rm llama3.1:8b-prefix-stable-v1
```

删除派生标签不会删除 `llama3.1:8b`。

## 限制

- 上述模板仅适用于经过测试的 `llama3.1:8b` 工具调用格式。
- Ollama 或模型发布者可能会在后续版本中更新默认模板。
- 在将自定义模板用于无人值守工作负载之前，请验证多次工具调用、工具错误、并行调用和长对话。
- 更高的缓存比率可以减少提示评估，但模型生成、工具执行、进程启动和存储仍可能主导端到端延迟。
- 多个 Ollama 槽位会改变缓存调度，并可能产生不同结果。

## 相关 nanobot 文档

- [提供商手册：Ollama 本地模型](../provider-cookbook-zh.md#recipe-ollama-local-model)
- [提供商和模型：Ollama](../providers-zh.md#ollama)
- [故障排除](../troubleshooting-zh.md)
