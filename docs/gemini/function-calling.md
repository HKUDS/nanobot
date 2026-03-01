# Function Calling

> **Status: Implemented** — AUTO mode only
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/function-calling

## What It Is

Enables the model to invoke external functions by generating structured function call requests with arguments. The bridge between natural language and real-world actions.

## Gemini API Capabilities

### Modes

| Mode | Behavior |
|------|----------|
| **AUTO** (default) | Model decides: call a function or respond with text |
| **ANY** | Model must call a function; can restrict via `allowed_function_names` |
| **NONE** | Function calling disabled |
| **VALIDATED** (preview) | Model chooses function or text, with strict schema adherence |

### Features

- **Parallel function calling** — multiple independent functions in one turn
- **Compositional calling** — sequential chaining where one output feeds the next
- **Automatic calling** (Python SDK) — SDK handles execution loop automatically
- **Multimodal responses** (Gemini 3) — function results can include images, PDFs
- **MCP support** — Model Context Protocol for external tool servers
- **Function declaration schema** — name, description, parameters (OpenAPI subset)

### Best practices

- Limit active tools to 10–20 for accuracy
- Use `enum` for fixed-value parameters
- Low temperature (0) for deterministic calling
- Validate calls with significant consequences before execution

## Nanobot Implementation

**Provider:** `scorpion/providers/gemini_provider.py`

**Tool conversion (lines 196-211):**
```python
@staticmethod
def _convert_tools(tools) -> list[types.Tool]:
    # OpenAI format → Gemini FunctionDeclaration
    declarations.append(types.FunctionDeclaration(
        name=name, description=desc, parameters=params,
    ))
    return [types.Tool(function_declarations=declarations)]
```

**Mode config (lines 58-62):**
```python
config.tool_config = types.ToolConfig(
    function_calling_config=types.FunctionCallingConfig(mode="AUTO"),
)
```

**Response parsing (lines 230-236):**
```python
if part.function_call:
    fc = part.function_call
    tool_calls.append(ToolCallRequest(
        id=fc.id or _short_id(),
        name=fc.name,
        arguments=dict(fc.args) if fc.args else {},
    ))
```

**FunctionResponse handling (lines 146-156):**
```python
# Tool results → types.FunctionResponse
parts = [types.Part(
    function_response=types.FunctionResponse(
        name=fn_name,
        response={"result": result_text},
    ),
)]
```

**What's implemented:**
- AUTO mode (hardcoded)
- OpenAI → Gemini tool definition conversion
- FunctionCall parsing with ID generation
- FunctionResponse round-trip
- JSON argument repair via `json_repair`

**What's missing:**
- ANY / NONE / VALIDATED modes
- Parallel function execution (calls are sequential in agent loop)
- Multimodal function responses
- MCP integration via Gemini (scorpion has its own MCP client)
- `allowed_function_names` filtering
