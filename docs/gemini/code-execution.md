# Code Execution

> **Status: Not implemented** — scorpion has agent-side shell execution
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/code-execution

## What It Is

Gemini generates and runs Python code in a sandboxed environment. Iterates on results (up to 5 retries) until arriving at a final output. No infrastructure needed.

## Gemini API Capabilities

### Configuration

```python
tools = [types.Tool(code_execution=types.ToolCodeExecution())]
```

### Features

- **Python only** — generates and executes Python
- **Iterative refinement** — up to 5 attempts on errors
- **30-second runtime** per execution
- **50+ preinstalled libraries:** NumPy, Pandas, Matplotlib, TensorFlow, scikit-learn, OpenCV, SymPy, etc.
- **Graph rendering** via Matplotlib
- **CSV/text file input** support
- **Image analysis** (Gemini 3 Flash) — auto-detects details, generates annotations
- **No billing** for code execution itself (just input/output tokens)
- Combinable with Google Search

### Response parts

1. `text` — model's explanation
2. `executable_code` — generated Python
3. `code_execution_result` — execution output and status

### Limitations

- Python only
- Cannot return media files (only text/graphs)
- Cannot install custom libraries
- 30-second timeout

## Nanobot Implementation

**Current code execution:** Agent-side shell tool (`scorpion/agent/tools/shell.py`)

```python
# ExecTool: runs shell commands via subprocess
# Supports any language/command, not just Python
# Has safety guards (regex blocklists for destructive commands)
# Configurable timeout (default 60s)
```

This is more powerful (any shell command) but less safe than Gemini's sandboxed Python. They serve different purposes.

**What Gemini Code Execution would enable:**
- Zero-infrastructure sandboxed execution
- No security risk (runs in Google's sandbox)
- Pre-installed data science libraries
- Matplotlib graph generation
- Iterative refinement by the model
- Could complement the existing shell tool
