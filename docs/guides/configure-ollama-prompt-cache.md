# Reuse Ollama Prompt Cache to Reduce Repeated Processing

Ollama can reuse work from an earlier prompt when the beginning of the prompt stays the same. Some model templates move or remove tool instructions as a conversation switches between user, assistant, and tool messages, so Ollama must process much of the prompt again. On slower local hardware, this can add tens of seconds to a tool-using turn.

This guide shows how to diagnose that specific pattern and create a derived `llama3.1:8b` tag with a prefix-stable tool template. It does not modify nanobot or overwrite the original Ollama model.

## What you will build

- a repeatable two-turn cache check
- an optional derived `llama3.1:8b-prefix-stable-v1` Ollama tag
- a nanobot model preset that uses the derived tag

## When to use this

Use this guide when all of the following are true:

- direct Ollama responses are reasonably fast;
- nanobot becomes slow after the model calls a tool;
- Ollama logs show a long main prompt, a much shorter tool follow-up, and low initial cache reuse on the next main prompt;
- the model is `llama3.1:8b` with a template that renders concrete tools only for the final user message.

Do not apply this template to another model family without checking that model's tool-call format first.

## Diagnose the rendered prompt

Stop any existing Ollama process, then start a single-slot debug server. A single slot makes the cache sequence easier to read.

**macOS or Linux**

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

In another terminal, use a fresh session and explicitly request a tool so both turns exercise the agent loop:

```bash
nanobot agent --session cli:ollama-cache-check \
  --message "Use the exec tool to calculate 2+2, then answer"
nanobot agent --session cli:ollama-cache-check \
  --message "Use the exec tool to calculate 4+7, then answer"
```

In the Ollama output, find each `new prompt` line and the first `cached n_tokens` line that follows it. Later increasing `cached n_tokens` lines are prompt-evaluation progress, not additional initial cache hits.

A cache-unfriendly tool template may produce a pattern like this:

```text
turn 1 main:             2 / 8460 initially cached
turn 1 tool follow-up: 3713 / 3758 initially cached
turn 2 main:          3767 / 8519 initially cached
```

The cache is working, but the next main request can reuse only the shorter prompt. Hardware throughput determines how expensive the remaining evaluation is.

To inspect the API request bodies as well, add `OLLAMA_DEBUG_LOG_REQUESTS=1` before starting Ollama. These logs can contain system prompts, workspace context, and user messages. Keep them local and disable request logging after diagnosis.

## Why the default template can limit cache reuse

The tested `llama3.1:8b` template conditionally expands the tool definitions inside a user message:

```gotemplate
{{- if and $.Tools $last }}
  ... render tool definitions ...
{{- end }}
```

The first request ends with a user message, so the tools are rendered there. After nanobot appends an assistant tool call and its result, that user message is no longer last, so the same API request history renders without the concrete tool block. On the next user turn, the tools reappear at a new position.

This is a model-template behavior. At the API boundary, nanobot continues to append the assistant tool call and tool result and sends the same tool definitions.

## Create a prefix-stable derived model

Create `PrefixStable.Modelfile` with the content below. The template keeps concrete tool definitions in the system block, where they remain in the same position across user and tool messages.

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

Create the new tag:

```bash
ollama create llama3.1:8b-prefix-stable-v1 -f PrefixStable.Modelfile
ollama list
```

Ollama reuses the existing model layers. The new tag adds a small template and manifest instead of copying the base weights.

## Select the derived model in nanobot

Open **Settings → Models → New preset**, select your Ollama connection, enter the derived model name, and save. Use **Enable preset** if it is disabled, then drag it to the first enabled position, marked **Primary**. This saves the default model used by sessions without their own model selection, including the fresh CLI session below.

Run the CLI commands with the same nanobot home as the WebUI. If the WebUI uses a custom home, add `--home <path>` before each subcommand.

<details>
<summary>Manual configuration</summary>

Merge this preset into your instance's `config.json` to make it the default:

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434/v1"
    }
  },
  "modelPresets": {
    "Ollama Llama 3.1 prefix-stable": {
      "provider": "ollama",
      "model": "llama3.1:8b-prefix-stable-v1",
      "maxTokens": 2048,
      "contextWindowTokens": 16384,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "Ollama Llama 3.1 prefix-stable"
    }
  }
}
```

</details>

Run `nanobot status` and confirm that **Model** shows `llama3.1:8b-prefix-stable-v1`, then repeat the two-turn check. If `cli:ollama-stable-check` already exists with a saved model selection, use a new session name for both turns.

```bash
nanobot status
nanobot agent --session cli:ollama-stable-check \
  --message "Use the exec tool to calculate 2+2, then answer"
nanobot agent --session cli:ollama-stable-check \
  --message "Use the exec tool to calculate 4+7, then answer"
```

In one controlled test with Ollama 0.32.1, `llama3.1:8b`, and one slot, the second main request improved from `3767 / 8519` initially cached (44.22%) to `8505 / 8520` (99.82%). The number of re-evaluated tokens fell from 4752 to 15. Treat these numbers as a diagnostic example, not a performance guarantee.

## Roll back

In **Settings → Models**, move the original preset back to the first enabled position and disable the derived preset. For conversations with a saved model selection, select the original preset in the composer as well.

<details>
<summary>Manual configuration</summary>

Set `agents.defaults.modelPreset` back to the original preset in your instance's `config.json`.

</details>

When no configuration or session uses the derived tag, remove it with:

```bash
ollama rm llama3.1:8b-prefix-stable-v1
```

Removing the derived tag does not remove `llama3.1:8b`.

## Limitations

- The template above is specific to the tested `llama3.1:8b` tool-call format.
- Ollama or the model publisher may update the stock template in a later release.
- Validate multiple tool calls, tool errors, parallel calls, and long conversations before using a custom template for unattended workloads.
- A higher cache ratio reduces prompt evaluation, but model generation, tool execution, process startup, and storage can still dominate end-to-end latency.
- Multiple Ollama slots change cache scheduling and may produce different results.

## Related nanobot docs

- [Provider Cookbook: Ollama Local Model](../provider-cookbook.md#recipe-ollama-local-model)
- [Providers and Models: Ollama](../providers.md#ollama)
- [Troubleshooting](../troubleshooting.md)
